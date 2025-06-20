# File: INKWISPS_post.py
import os
import time
import json
import logging
import requests
import dropbox
from telegram import Bot
from datetime import datetime, timedelta
from pytz import timezone, utc
import subprocess
import tempfile
import shutil

class DropboxToInstagramUploader:
    DROPBOX_TOKEN_URL = "https://api.dropbox.com/oauth2/token"
    INSTAGRAM_API_BASE = "https://graph.facebook.com/v18.0"
    INSTAGRAM_REEL_STATUS_RETRIES = 20
    INSTAGRAM_REEL_STATUS_WAIT_TIME = 5

    def __init__(self):
        self.script_name = "inkwisps_post.py"
        self.ist = timezone('Asia/Kolkata')
        self.account_key = "inkwisps"
        self.schedule_file = "scheduler/config.json"

        # Logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()]
        )
        self.logger = logging.getLogger()

        # Secrets from GitHub environment
        self.instagram_access_token = os.getenv("IG_INKWISPS_TOKEN")
        self.instagram_account_id = os.getenv("IG_INKWISPS_ID")
        self.dropbox_app_key = os.getenv("DROPBOX_INKWISPS_APP_KEY")
        self.dropbox_app_secret = os.getenv("DROPBOX_INKWISPS_APP_SECRET")
        self.dropbox_refresh_token = os.getenv("DROPBOX_INKWISPS_REFRESH")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        self.dropbox_folder = "/inkwisps"
        self.telegram_bot = Bot(token=self.telegram_bot_token)

        self.start_time = time.time()

    def send_message(self, msg, level=logging.INFO):
        prefix = f"[{self.script_name}]\n"
        full_msg = prefix + msg
        try:
            self.telegram_bot.send_message(chat_id=self.telegram_chat_id, text=full_msg)
            # Also log the message to console with the specified level
            if level == logging.ERROR:
                self.logger.error(full_msg)
            else:
                self.logger.info(full_msg)
        except Exception as e:
            self.logger.error(f"Telegram send error for message '{full_msg}': {e}")

    def refresh_dropbox_token(self):
        self.logger.info("Refreshing Dropbox token...")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.dropbox_refresh_token,
            "client_id": self.dropbox_app_key,
            "client_secret": self.dropbox_app_secret,
        }
        r = requests.post(self.DROPBOX_TOKEN_URL, data=data)
        if r.status_code == 200:
            new_token = r.json().get("access_token")
            self.logger.info("Dropbox token refreshed.")
            return new_token
        else:
            self.send_message("❌ Dropbox refresh failed: " + r.text)
            raise Exception("Dropbox refresh failed.")

    def list_dropbox_files(self, dbx):
        try:
            files = dbx.files_list_folder(self.dropbox_folder).entries
            valid_exts = ('.mp4', '.mov', '.jpg', '.jpeg', '.png')
            return [f for f in files if f.name.lower().endswith(valid_exts)]
        except Exception as e:
            self.send_message(f"❌ Dropbox folder read failed: {e}", level=logging.ERROR)
            return []

    def get_caption_from_config(self):
        try:
            with open(self.schedule_file, 'r') as f:
                config = json.load(f)
            
            # Get today's caption from config
            today = datetime.now(self.ist).strftime("%A")
            day_config = config.get(self.account_key, {}).get(today, {})
            caption = day_config.get("caption", "")
            
            if not caption:
                self.send_message("⚠️ No caption found in config for today", level=logging.WARNING)
                return "✨ #ink_wisps ✨"  # Default caption if none found
            
            return caption
        except Exception as e:
            self.send_message(f"❌ Failed to read caption from config: {e}", level=logging.ERROR)
            return "✨ #ink_wisps ✨"  # Default caption if config read fails

    def setup_file_logger(self):
        self.log_file = os.path.join(tempfile.gettempdir(), f"{self.script_name}.log")
        file_handler = logging.FileHandler(self.log_file)
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def send_log_file(self):
        try:
            with open(self.log_file, 'rb') as f:
                self.telegram_bot.send_document(chat_id=self.telegram_chat_id, document=f)
        except Exception as e:
            self.logger.error(f"Failed to send log file: {e}")

    def check_and_convert_video(self, dbx, file):
        """
        Check if the video meets Instagram requirements. If not, convert it using ffmpeg (streaming from Dropbox),
        upload to Dropbox /temp, and return the new file metadata. No local storage is used for the final file.
        """
        # Instagram requirements
        min_duration = 3
        max_duration = 90
        min_width = 500
        max_filesize = 100 * 1024 * 1024  # 100MB
        allowed_codecs = ['h264', 'aac']
        temp_link = dbx.files_get_temporary_link(file.path_lower).link
        # Probe video using ffprobe
        ffprobe_cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
            'stream=width,height,codec_name,duration', '-of', 'json', temp_link
        ]
        try:
            probe = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
            info = json.loads(probe.stdout)
            stream = info['streams'][0]
            width = int(stream['width'])
            height = int(stream['height'])
            codec = stream['codec_name']
            duration = float(stream['duration'])
        except Exception as e:
            self.logger.error(f"ffprobe failed: {e}")
            return file  # fallback: try to upload as is
        # Check requirements
        needs_convert = (
            codec != 'h264' or
            width < min_width or
            duration < min_duration or duration > max_duration or
            file.size > max_filesize
        )
        if not needs_convert:
            return file  # Already compliant
        # Convert using ffmpeg, stream from Dropbox, output to temp file
        self.logger.info(f"Converting video {file.name} to Instagram format...")
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_out:
            temp_out_path = temp_out.name
        ffmpeg_cmd = [
            'ffmpeg', '-y', '-i', temp_link,
            '-vf', f'scale={max(width,540)}:-2',
            '-c:v', 'libx264', '-preset', 'fast', '-profile:v', 'main', '-level', '3.1',
            '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
            '-t', str(max_duration),
            temp_out_path
        ]
        try:
            subprocess.run(ffmpeg_cmd, check=True)
            # Upload to Dropbox /temp
            with open(temp_out_path, 'rb') as f:
                temp_dropbox_path = f"/temp/{file.name}_insta.mp4"
                dbx.files_upload(f.read(), temp_dropbox_path, mode=dropbox.files.WriteMode.overwrite)
            os.remove(temp_out_path)
            # Get new file metadata
            new_file = dbx.files_get_metadata(temp_dropbox_path)
            self.logger.info(f"Converted and uploaded to {temp_dropbox_path}")
            return new_file
        except Exception as e:
            self.logger.error(f"ffmpeg conversion/upload failed: {e}")
            if os.path.exists(temp_out_path):
                os.remove(temp_out_path)
            return file  # fallback: try to upload as is

    def post_to_instagram(self, dbx, file, caption):
        name = file.name
        ext = name.lower()
        media_type = "REELS" if ext.endswith((".mp4", ".mov")) else "IMAGE"
        # For video, check/convert first
        if media_type == "REELS":
            file = self.check_and_convert_video(dbx, file)
        temp_link = dbx.files_get_temporary_link(file.path_lower).link
        file_size = f"{file.size / 1024 / 1024:.2f}MB"
        total_files = len(self.list_dropbox_files(dbx))
        self.send_message(f"🚀 Uploading: {name}\n📂 Type: {media_type}\n📐 Size: {file_size}\n📦 Remaining: {total_files}")
        upload_url = f"{self.INSTAGRAM_API_BASE}/{self.instagram_account_id}/media"
        data = {
            "access_token": self.instagram_access_token,
            "caption": caption
        }
        if media_type == "REELS":
            data.update({"media_type": "REELS", "video_url": temp_link, "share_to_feed": "true"})
        else:
            data["image_url"] = temp_link
        try:
            res = requests.post(upload_url, data=data)
            if res.status_code != 200:
                self.logger.error(f"Instagram upload error: {res.text}")
                err = res.json().get("error", {}).get("message", "Unknown")
                code = res.json().get("error", {}).get("code", "N/A")
                self.send_message(f"❌ Failed: {name}\n🧾 Error: {err}\n🪪 Code: {code}", level=logging.ERROR)
                self.send_log_file()
                return False
            creation_id = res.json()["id"]
            if media_type == "REELS":
                for _ in range(self.INSTAGRAM_REEL_STATUS_RETRIES):
                    status_res = requests.get(
                        f"{self.INSTAGRAM_API_BASE}/{creation_id}?fields=status_code&access_token={self.instagram_access_token}"
                    )
                    status = status_res.json()
                    if status.get("status_code") == "FINISHED":
                        break
                    elif status.get("status_code") == "ERROR":
                        self.logger.error(f"IG processing failed: {name}, status: {status}")
                        self.send_message(f"❌ IG processing failed: {name}\n{status}", level=logging.ERROR)
                        self.send_log_file()
                        return False
                    time.sleep(self.INSTAGRAM_REEL_STATUS_WAIT_TIME)
            publish_url = f"{self.INSTAGRAM_API_BASE}/{self.instagram_account_id}/media_publish"
            pub = requests.post(publish_url, data={"creation_id": creation_id, "access_token": self.instagram_access_token})
            if pub.status_code == 200:
                self.send_message(f"✅ Uploaded: {name}\n📦 Files left: {total_files - 1}")
                dbx.files_delete_v2(file.path_lower)
                # If temp file, also delete from /temp
                if media_type == "REELS" and file.path_lower.startswith("/temp/"):
                    try:
                        dbx.files_delete_v2(file.path_lower)
                    except Exception as e:
                        self.logger.error(f"Failed to delete temp file: {e}")
                return True
            else:
                self.logger.error(f"Instagram publish error: {pub.text}")
                self.send_message(f"❌ Publish failed: {name}\n{pub.text}", level=logging.ERROR)
                self.send_log_file()
                return False
        except Exception as e:
            self.logger.error(f"Instagram API exception: {e}")
            self.send_message(f"❌ Instagram API exception: {e}", level=logging.ERROR)
            self.send_log_file()
            return False

    def authenticate_dropbox(self):
        """Authenticate with Dropbox and return the client."""
        try:
            access_token = self.refresh_dropbox_token()
            return dropbox.Dropbox(oauth2_access_token=access_token)
        except Exception as e:
            self.send_message(f"❌ Dropbox authentication failed: {str(e)}", level=logging.ERROR)
            raise

    def select_media_file(self, dbx):
        """Select the first available media file from Dropbox."""
        try:
            files = self.list_dropbox_files(dbx)
            if not files:
                self.send_message("📭 No eligible media found in Dropbox.", level=logging.INFO)
                return None
            return files[0]  # Return the first available file
        except Exception as e:
            self.send_message(f"❌ Failed to select media file: {str(e)}", level=logging.ERROR)
            raise

    def upload_and_publish(self, dbx, file, caption):
        """Upload and publish the selected media file to Instagram."""
        try:
            if self.post_to_instagram(dbx, file, caption):
                self.send_message("✅ Successfully posted one image", level=logging.INFO)
                return True
            return False
        except Exception as e:
            self.send_message(f"❌ Failed to upload and publish: {str(e)}", level=logging.ERROR)
            raise

    def run(self):
        self.setup_file_logger()
        self.send_message(f"📡 Run started at: {datetime.now(self.ist).strftime('%Y-%m-%d %H:%M:%S')}", level=logging.INFO)
        try:
            caption = self.get_caption_from_config()
            dbx = self.authenticate_dropbox()
            file = self.select_media_file(dbx)
            if not file:
                return
            self.upload_and_publish(dbx, file, caption)
        except Exception as e:
            self.logger.error(f"Script crashed: {e}")
            self.send_message(f"❌ Script crashed:\n{str(e)}", level=logging.ERROR)
            self.send_log_file()
            raise
        finally:
            duration = time.time() - self.start_time
            self.send_message(f"🏁 Run complete in {duration:.1f} seconds", level=logging.INFO)

if __name__ == "__main__":
    DropboxToInstagramUploader().run()
