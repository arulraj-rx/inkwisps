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
from moviepy.editor import VideoFileClip

class DropboxToInstagramUploader:
    DROPBOX_TOKEN_URL = "https://api.dropbox.com/oauth2/token"
    INSTAGRAM_API_BASE = "https://graph.facebook.com/v18.0"
    INSTAGRAM_REEL_STATUS_RETRIES = 10
    INSTAGRAM_REEL_STATUS_WAIT_TIME = 15

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
        self.meta_token = os.getenv("META_TOKEN")
        self.ig_id = os.getenv("IG_ID")
        self.fb_page_id = os.getenv("FB_PAGE_ID")
        
        # Telegram configuration
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        self.dropbox_key = os.getenv("DROPBOX_APP_KEY")
        self.dropbox_secret = os.getenv("DROPBOX_APP_SECRET")
        self.dropbox_refresh = os.getenv("DROPBOX_REFRESH_TOKEN")

        self.dropbox_folder = "/inkwisp"
        if self.telegram_token:
            self.telegram_bot = Bot(token=self.telegram_token)
        else:
            self.telegram_bot = None

        self.start_time = time.time()
        self.session = requests.Session()

    def send_message(self, msg, level=logging.INFO):
        prefix = f"[{self.script_name}]\n"
        full_msg = prefix + msg
        try:
            if self.telegram_bot and self.telegram_chat_id:
                self.telegram_bot.send_message(chat_id=self.telegram_chat_id, text=full_msg)
            # Also log the message to console with the specified level
            if level == logging.ERROR:
                self.logger.error(full_msg)
            else:
                self.logger.info(full_msg)
        except Exception as e:
            self.logger.error(f"Telegram send error for message '{full_msg}': {e}")

    def log_console_only(self, msg, level=logging.INFO):
        """Log message to console only, not to Telegram."""
        prefix = f"[{self.script_name}]\n"
        full_msg = prefix + msg
        if level == logging.ERROR:
            self.logger.error(full_msg)
        else:
            self.logger.info(full_msg)

    def send_token_expiry_info(self):
        """Get comprehensive token expiry info using debug_token endpoint."""
        try:
            url = "https://graph.facebook.com/debug_token"
            params = {
                "input_token": self.meta_token,
                "access_token": self.meta_token
            }
            res = self.session.get(url, params=params)
            
            if res.status_code != 200:
                self.send_message(f"❌ Failed to check token: {res.text}", level=logging.ERROR)
                return

            data = res.json().get("data", {})
            is_valid = data.get("is_valid", False)
            expires_at = data.get("expires_at")  # epoch timestamp
            data_access_expires_at = data.get("data_access_expires_at")  # epoch timestamp

            if is_valid:
                message_parts = ["🔐 Meta Token Status:", "✅ Token is valid."]
                
                if expires_at:
                    expiry_dt = datetime.utcfromtimestamp(expires_at)
                    delta = expiry_dt - datetime.utcnow()
                    message_parts.append(f"⏳ Token expires on {expiry_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC ({delta.days} days left)")
                else:
                    message_parts.append("🔐 Token does not expire (likely a Page or system token)")

                if data_access_expires_at:
                    daa_expiry_dt = datetime.utcfromtimestamp(data_access_expires_at)
                    daa_delta = daa_expiry_dt - datetime.utcnow()
                    message_parts.append(f"📅 Data access expires on {daa_expiry_dt.strftime('%Y-%m-%d %H:%M:%S')} UTC ({daa_delta.days} days left)")
                
                self.send_message("\n".join(message_parts), level=logging.INFO)
            else:
                self.send_message("⚠️ Token is invalid or expired.", level=logging.WARNING)
                
        except Exception as e:
            self.send_message(f"⚠️ Could not retrieve token expiry info: {str(e)}", level=logging.WARNING)

    def get_page_access_token(self):
        """Fetch short-lived Page Access Token from long-lived user token."""
        try:
            self.log_console_only("🔐 Fetching Page Access Token from Meta API...", level=logging.INFO)
            url = f"https://graph.facebook.com/v18.0/me/accounts"
            params = {"access_token": self.meta_token}
            
            self.log_console_only(f"📡 API URL: {url}", level=logging.INFO)
            
            start_time = time.time()
            res = self.session.get(url, params=params)
            request_time = time.time() - start_time
            
            self.log_console_only(f"⏱️ Page token request completed in {request_time:.2f} seconds", level=logging.INFO)
            self.log_console_only(f"📊 Response status: {res.status_code}", level=logging.INFO)

            if res.status_code != 200:
                self.send_message(f"❌ Failed to fetch Page token: {res.text}", level=logging.ERROR)
                return None

            pages = res.json().get("data", [])
            self.log_console_only(f"🔍 Found {len(pages)} pages in user account", level=logging.INFO)
            
            # Show all available pages with details (console only)
            self.log_console_only("📋 Available Pages:", level=logging.INFO)
            for i, page in enumerate(pages):
                page_id = page.get("id", "Unknown")
                page_name = page.get("name", "Unknown")
                category = page.get("category", "Unknown")
                tasks = page.get("tasks", [])
                page_access_token = page.get("access_token", "Not available")
                
                self.log_console_only(f"📄 Page {i+1}:", level=logging.INFO)
                self.log_console_only(f"   📝 Name: {page_name}", level=logging.INFO)
                self.log_console_only(f"   🆔 ID: {page_id}", level=logging.INFO)
                self.log_console_only(f"   📂 Category: {category}", level=logging.INFO)
                self.log_console_only(f"   🔧 Tasks: {', '.join(tasks)}", level=logging.INFO)
                self.log_console_only(f"   🔐 Access Token: {page_access_token[:20]}..." if page_access_token != "Not available" else "   🔐 Access Token: Not available", level=logging.INFO)
                
                # Check if this is the target page
                if page_id == self.fb_page_id:
                    self.log_console_only(f"   ✅ MATCH FOUND! This is your target page", level=logging.INFO)
                    
                    # Use the page access token directly from the response
                    if page_access_token and page_access_token != "Not available":
                        self.send_message(f"✅ Page Access Token fetched successfully for: {page_name} (ID: {self.fb_page_id})")
                        self.log_console_only(f"🔐 Using page access token: {page_access_token[:20]}...", level=logging.INFO)
                        return page_access_token
                    else:
                        self.send_message(f"❌ No access token found for page: {page_name}", level=logging.ERROR)
                        return None
                else:
                    self.log_console_only(f"   ❌ Not matching target page ID: {self.fb_page_id}", level=logging.INFO)

            # If no match found, show configuration help
            self.send_message(f"⚠️ Page ID {self.fb_page_id} not found in user's account list.", level=logging.WARNING)
            self.log_console_only("💡 To fix this, update your FB_PAGE_ID environment variable with one of the page IDs shown above.", level=logging.INFO)
            return None
        except Exception as e:
            self.send_message(f"❌ Exception during Page token fetch: {e}", level=logging.ERROR)
            return None

    def refresh_dropbox_token(self):
        self.logger.info("Refreshing Dropbox token...")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.dropbox_refresh,
            "client_id": self.dropbox_key,
            "client_secret": self.dropbox_secret,
        }
        r = self.session.post(self.DROPBOX_TOKEN_URL, data=data)
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
            
            caption = day_config.get("caption", "✨ #inkwisps ✨")
            description = day_config.get("description", caption)  # Fallback to caption if missing
            
            if not caption:
                self.send_message("⚠️ No caption found in config for today", level=logging.WARNING)
            
            return caption, description
        except Exception as e:
            self.send_message(f"❌ Failed to read caption/description from config: {e}", level=logging.ERROR)
            return "✨ #inkwisps ✨", "✨ #inkwisps ✨"

    def build_caption_with_filename(self, file, original_caption):
        base_name = os.path.splitext(file.name)[0]
        base_name = base_name.replace('_', ' ')
        first_line = base_name[:100]
        return f"{first_line}\n\n{original_caption}"

    def post_to_instagram(self, dbx, file, caption, description):
        name = file.name
        ext = name.lower()
        media_type = "REELS" if ext.endswith((".mp4", ".mov")) else "IMAGE"

        self.send_message(f"🚀 Starting upload process for: {name}", level=logging.INFO)
        
        temp_link = dbx.files_get_temporary_link(file.path_lower).link
        file_size = f"{file.size / 1024 / 1024:.2f}MB"
        total_files = len(self.list_dropbox_files(dbx))

        self.log_console_only(f"📸 Instagram upload details:\n📂 Type: {media_type}\n📐 Size: {file_size}\n📦 Remaining: {total_files}")

        # Get Facebook page access token for both Instagram and Facebook
        self.log_console_only("🔐 Step 1: Retrieving Facebook Page Access Token...", level=logging.INFO)
        page_token = self.get_page_access_token()
        if not page_token:
            self.send_message("❌ Could not retrieve Facebook Page access token. Aborting upload.", level=logging.ERROR)
            return False

        self.log_console_only("✅ Facebook Page Access Token retrieved successfully", level=logging.INFO)

        # Test the page token to ensure it works
        if not self.test_page_token(page_token):
            self.send_message("❌ Page token test failed. Aborting upload.", level=logging.ERROR)
            return False

        # Check if Instagram is properly connected to the Facebook page
        if not self.check_instagram_page_connection(page_token):
            self.send_message("❌ Instagram account not properly connected to Facebook page. Aborting upload.", level=logging.ERROR)
            return False

        # Build captions with file name as first line
        caption = self.build_caption_with_filename(file, caption)
        description = self.build_caption_with_filename(file, description)

        upload_url = f"{self.INSTAGRAM_API_BASE}/{self.ig_id}/media"
        data = {
            "access_token": page_token,
            "caption": caption
        }

        if media_type == "REELS":
            data.update({"media_type": "REELS", "video_url": temp_link, "share_to_feed": "false"})
        else:
            data["image_url"] = temp_link

        self.log_console_only("🔄 Step 2: Sending media creation request to Instagram API...", level=logging.INFO)
        self.log_console_only(f"📡 API URL: {upload_url}", level=logging.INFO)
        
        start_time = time.time()
        res = self.session.post(upload_url, data=data)
        request_time = time.time() - start_time
        
        self.log_console_only(f"⏱️ API request completed in {request_time:.2f} seconds", level=logging.INFO)
        self.log_console_only(f"📊 Response status: {res.status_code}", level=logging.INFO)
        
        if res.status_code != 200:
            err = res.json().get("error", {}).get("message", "Unknown")
            code = res.json().get("error", {}).get("code", "N/A")
            self.send_message(f"❌ Instagram upload failed: {name}\n📸 Error: {err}\n📸 Code: {code}\n📸 Status: {res.status_code}", level=logging.ERROR)
            return False, media_type

        creation_id = res.json().get("id")
        if not creation_id:
            self.send_message(f"❌ No media ID returned for: {name}", level=logging.ERROR)
            return False, media_type

        self.log_console_only(f"✅ Media creation successful! Creation ID: {creation_id}", level=logging.INFO)

        if media_type == "REELS":
            self.log_console_only("⏳ Step 3: Processing video for Instagram...", level=logging.INFO)
            processing_start = time.time()
            for attempt in range(self.INSTAGRAM_REEL_STATUS_RETRIES):
                self.log_console_only(f"🔄 Processing attempt {attempt + 1}/{self.INSTAGRAM_REEL_STATUS_RETRIES}", level=logging.INFO)
                
                status_response = self.session.get(
                    f"{self.INSTAGRAM_API_BASE}/{creation_id}?fields=status_code&access_token={page_token}"
                )
                
                if status_response.status_code != 200:
                    self.send_message(f"❌ Status check failed: {status_response.status_code}", level=logging.ERROR)
                    return False
                
                status = status_response.json()
                current_status = status.get("status_code", "UNKNOWN")
                
                self.log_console_only(f"📊 Current status: {current_status}", level=logging.INFO)
                
                if current_status == "FINISHED":
                    processing_time = time.time() - processing_start
                    self.log_console_only(f"✅ Instagram video processing completed in {processing_time:.2f} seconds!", level=logging.INFO)
                    
                    # Wait 8 seconds after FINISHED status before publishing (reduced from 15)
                    self.log_console_only("⏳ Waiting 15 seconds before publishing...", level=logging.INFO)
                    time.sleep(15)
                    break
                elif current_status == "ERROR":
                    self.send_message(f"❌ Instagram processing failed: {name}\n📸 Status: ERROR", level=logging.ERROR)
                    return False
                
                self.log_console_only(f"⏳ Waiting {self.INSTAGRAM_REEL_STATUS_WAIT_TIME} seconds before next check...", level=logging.INFO)
                time.sleep(self.INSTAGRAM_REEL_STATUS_WAIT_TIME)

        self.log_console_only("📤 Step 4: Publishing to Instagram...", level=logging.INFO)
        publish_url = f"{self.INSTAGRAM_API_BASE}/{self.ig_id}/media_publish"
        publish_data = {"creation_id": creation_id, "access_token": page_token}
        
        self.log_console_only(f"📡 Publishing to: {publish_url}", level=logging.INFO)
        
        publish_start = time.time()
        pub = self.session.post(publish_url, data=publish_data)
        publish_time = time.time() - publish_start
        
        self.log_console_only(f"⏱️ Publish request completed in {publish_time:.2f} seconds", level=logging.INFO)
        self.log_console_only(f"📊 Publish response status: {pub.status_code}", level=logging.INFO)
        
        # Track Instagram and Facebook results separately
        instagram_success = False
        facebook_success = False
        
        if pub.status_code == 200:
            response_data = pub.json()
            instagram_id = response_data.get("id", "Unknown")
            
            if not instagram_id:
                self.send_message("⚠️ Instagram publish succeeded but no media ID returned", level=logging.WARNING)
                instagram_success = False
            else:
                self.send_message(f"✅ Instagram post published successfully!\n📸 Media ID: {instagram_id}\n📸 Account ID: {self.ig_id}\n📦 Files left: {total_files - 1}")
                instagram_success = True
                
                # Verify the post is live using the published media_id (not creation_id)
                self.verify_instagram_post_by_media_id(instagram_id, page_token)
            
            # Also post to Facebook Page for both REELS and IMAGE
            if media_type == "REELS":
                self.log_console_only("📘 Step 5: Starting Facebook Page upload...", level=logging.INFO)
                facebook_success = self.post_to_facebook_page(dbx, file, caption, page_token)
            elif media_type == "IMAGE":
                self.log_console_only("📘 Step 5: Starting Facebook Page upload for image...", level=logging.INFO)
                facebook_success = self.post_to_facebook_page(dbx, file, caption, page_token)
                # Telegram log for Facebook image upload
                if facebook_success:
                    self.send_message(f"✅ Facebook Page photo published successfully for file: {file.name}", level=logging.INFO)
                else:
                    self.send_message(f"❌ Facebook Page photo upload failed for file: {file.name}", level=logging.ERROR)
            else:
                facebook_success = True  # No Facebook post needed for other types
            
            # Return success status for both platforms
            return True, media_type, instagram_success, facebook_success
        else:
            error_msg = pub.json().get("error", {}).get("message", "Unknown error")
            error_code = pub.json().get("error", {}).get("code", "N/A")
            self.send_message(f"❌ Instagram publish failed: {name}\n📸 Error: {error_msg}\n📸 Code: {error_code}\n📸 Status: {pub.status_code}", level=logging.ERROR)
            # Do not attempt verification with creation_id, as it is invalid after publish
            return False, media_type, instagram_success, facebook_success

    def is_supported_aspect_ratio(self, video_path):
        clip = VideoFileClip(video_path)
        width, height = clip.size
        aspect_ratio = width / height
        duration = clip.duration
        self.log_console_only(f"🎬 Video duration: {duration:.2f}s", level=logging.INFO)
        if duration < 3 or duration > 90:
            self.send_message(f'❌ Video duration {duration:.2f}s not supported for Reels (must be 3–90s).', level=logging.ERROR)
            return False
        return 0.5625 <= aspect_ratio <= 1.7778

    def get_video_aspect_and_duration(self, video_url):
        """Download video to temp file, return (aspect_ratio, duration, temp_file_path)."""
        import tempfile
        import requests
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
        with requests.get(video_url, stream=True) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=8192):
                temp_file.write(chunk)
        temp_file.close()
        from moviepy.editor import VideoFileClip
        clip = VideoFileClip(temp_file.name)
        width, height = clip.size
        aspect_ratio = width / height
        duration = clip.duration
        return aspect_ratio, duration, temp_file.name

    def get_dropbox_video_metadata(self, dbx, file):
        """Get width, height, duration from Dropbox file metadata (no download)."""
        from dropbox.files import VideoMetadata, PhotoMetadata
        metadata = dbx.files_get_metadata(file.path_lower, include_media_info=True)
        if hasattr(metadata, 'media_info') and metadata.media_info:
            info = metadata.media_info.get_metadata()
            width = None
            height = None
            if getattr(info, 'dimensions', None) is not None:
                width = info.dimensions.width
                height = info.dimensions.height
            if isinstance(info, VideoMetadata):
                duration = info.duration / 1000.0  # ms to seconds
            else:
                duration = None
            return width, height, duration
        return None, None, None

    def post_to_facebook_page(self, dbx, file, caption, page_token=None, as_reel=None):
        """Publish the video to the Facebook Page as a Reel or regular video. Uses Dropbox metadata for decision."""
        import requests
        import os
        media_url = dbx.files_get_temporary_link(file.path_lower).link
        if not self.fb_page_id:
            self.send_message("⚠️ Facebook Page ID not configured, skipping Facebook post", level=logging.WARNING)
            return False
        if not page_token:
            self.log_console_only("🔐 Fetching fresh Facebook Page Access Token...", level=logging.INFO)
            page_token = self.get_page_access_token()
            if not page_token:
                self.send_message("❌ Could not retrieve Facebook Page access token. Aborting Facebook upload.", level=logging.ERROR)
                return False
        else:
            self.log_console_only("🔐 Using shared Facebook Page Access Token for Facebook upload", level=logging.INFO)
        # Use Dropbox metadata for decision
        width, height, duration = self.get_dropbox_video_metadata(dbx, file)
        aspect_ratio = width / height if width and height else None
        decision_msg = f"\n📦 File: {file.name}\n📏 Width: {width}\n📏 Height: {height}\n⏱️ Duration: {duration}s\n📐 Aspect Ratio: {aspect_ratio:.4f}" if aspect_ratio else f"\n📦 File: {file.name}\n📏 Width: {width}\n📏 Height: {height}\n⏱️ Duration: {duration}s\n📐 Aspect Ratio: N/A"
        # Strict 9:16 check for Reels
        if width is not None and height is not None and duration is not None and aspect_ratio is not None:
            # Only allow strict 9:16 portrait (e.g., 1080x1920, 720x1280) for Facebook Reels
            if height >= 960 and width >= 540 and abs(aspect_ratio - 0.5625) < 0.01:
                as_reel = True
                decision_msg += "\n🚀 Will upload as: Facebook Reel (strict 9:16 portrait)"
                self.log_console_only("✅ Strict 9:16 portrait detected. Will upload as Facebook Reel.", level=logging.INFO)
            else:
                as_reel = False
                decision_msg += f"\n🚀 Will upload as: Regular Facebook Video (aspect ratio: {aspect_ratio:.4f})"
                self.log_console_only(f"❌ Not strict 9:16 portrait (aspect ratio: {aspect_ratio:.4f}). Will upload as regular Facebook video.", level=logging.INFO)
        else:
            self.log_console_only("Could not get Dropbox video metadata, defaulting to regular video.", level=logging.WARNING)
            as_reel = False
            decision_msg += "\n🚀 Will upload as: Regular Facebook Video (metadata unavailable)"
        self.send_message(decision_msg, level=logging.INFO)
        if as_reel:
            self.log_console_only("📘 Starting Facebook Page upload (Reels API, hosted file)...", level=logging.INFO)
            # 1. Start upload session
            start_url = f"https://graph.facebook.com/v23.0/{self.fb_page_id}/video_reels"
            start_data = {"upload_phase": "start", "access_token": page_token}
            start_res = self.session.post(start_url, data=start_data)
            if start_res.status_code != 200:
                self.send_message(f"❌ Failed to start Facebook Reels upload session: {start_res.text}", level=logging.ERROR)
                return False
            video_id = start_res.json().get("video_id")
            upload_url = start_res.json().get("upload_url")
            if not video_id or not upload_url:
                self.send_message(f"❌ No video_id or upload_url returned: {start_res.text}", level=logging.ERROR)
                return False
            # 2. Upload video using hosted file (Dropbox temp link)
            headers = {
                "Authorization": f"OAuth {page_token}",
                "file_url": media_url
            }
            upload_res = self.session.post(upload_url, headers=headers)
            if upload_res.status_code != 200:
                self.send_message(f"❌ Facebook Reels video upload (hosted file) failed: {upload_res.text}", level=logging.ERROR)
                return False
            # 3. Finish and publish
            finish_data = {
                "upload_phase": "finish",
                "access_token": page_token,
                "video_id": video_id,
                "description": caption,
                "video_state": "PUBLISHED",
                "share_to_feed": "true"
            }
            finish_res = self.session.post(start_url, data=finish_data)
            if finish_res.status_code == 200:
                response_data = finish_res.json()
                fb_video_id = response_data.get("id", video_id)
                self.send_message(f"✅ Facebook Reel published successfully!\n📘 Video ID: {fb_video_id}\n📘 Page ID: {self.fb_page_id}")
                self.verify_facebook_post_by_video_id(fb_video_id, page_token)
                # Fetch and log the list of Reels for the Page
                try:
                    reels_url = f'https://graph.facebook.com/v23.0/{self.fb_page_id}/video_reels?access_token={page_token}'
                    reels_res = self.session.get(reels_url)
                    self.log_console_only(f'📄 Reels list response: {reels_res.text}', level=logging.INFO)
                except Exception as e:
                    self.log_console_only(f'⚠️ Could not fetch Reels list: {e}', level=logging.WARNING)
                return True
            else:
                self.send_message(f"❌ Facebook Reels publish failed: {finish_res.text}", level=logging.ERROR)
                return False
        else:
            self.log_console_only("📘 Starting Facebook Page upload (Regular Video)...", level=logging.INFO)
            # Detect if file is an image
            image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp')
            is_image = file.name.lower().endswith(image_exts)
            if is_image:
                self.log_console_only("🖼️ Detected image file. Uploading as Facebook photo.", level=logging.INFO)
                self.send_message(f"\n📦 File: {file.name}\n🖼️ Will upload as: Facebook Photo", level=logging.INFO)
                post_url = f"https://graph.facebook.com/{self.fb_page_id}/photos"
                self.log_console_only(f"🌐 Dropbox image URL: {media_url}", level=logging.INFO)
                # Check if Dropbox link is accessible
                try:
                    check_res = requests.get(media_url, timeout=10)
                    if check_res.status_code == 200:
                        self.log_console_only(f"✅ Dropbox link is accessible (status 200)", level=logging.INFO)
                    else:
                        self.log_console_only(f"❌ Dropbox link returned status {check_res.status_code}", level=logging.ERROR)
                except Exception as e:
                    self.log_console_only(f"❌ Exception checking Dropbox link: {e}", level=logging.ERROR)
                data = {
                    "access_token": page_token,
                    "url": media_url,
                    "caption": caption
                }
                try:
                    self.log_console_only("🔄 Sending image upload request to Facebook API...", level=logging.INFO)
                    self.log_console_only(f"📡 Facebook API URL: {post_url}", level=logging.INFO)
                    res = self.session.post(post_url, data=data)
                    self.log_console_only(f"📊 Facebook response status: {res.status_code}", level=logging.INFO)
                    try:
                        response_json = res.json()
                        self.log_console_only(f"📄 Facebook response: {json.dumps(response_json, indent=2)}", level=logging.INFO)
                    except:
                        self.log_console_only(f"📄 Facebook response text: {res.text}", level=logging.INFO)
                    if res.status_code == 200:
                        photo_id = res.json().get("id", "Unknown")
                        self.send_message(f"✅ Facebook Page photo published successfully!\n🖼️ Photo ID: {photo_id}\n📘 Page ID: {self.fb_page_id}")
                        return True
                    else:
                        error_msg = res.json().get("error", {}).get("message", "Unknown error")
                        self.send_message(f"❌ Facebook Page photo upload failed: {error_msg}", level=logging.ERROR)
                        return False
                except Exception as e:
                    self.send_message(f"❌ Facebook Page photo upload exception:\n🖼️ Error: {str(e)}", level=logging.ERROR)
                    return False
            else:
                self.log_console_only("📘 Starting Facebook Page upload (Regular Video)...", level=logging.INFO)
                post_url = f"https://graph.facebook.com/{self.fb_page_id}/videos"
                data = {
                    "access_token": page_token,
                    "file_url": media_url,
                    "description": caption
                }
                self.log_console_only(f"🔐 Using page token for Facebook upload: {page_token[:20]}...", level=logging.INFO)
                self.log_console_only(f"📄 Page ID for upload: {self.fb_page_id}", level=logging.INFO)
                self.log_console_only(f"📹 Video URL: {media_url[:50]}...", level=logging.INFO)
                self.log_console_only(f"📝 Caption: {caption[:50]}...", level=logging.INFO)
                self.log_console_only("🔄 Skipping token verification for Facebook upload...", level=logging.INFO)
                try:
                    self.log_console_only("🔄 Sending request to Facebook API...", level=logging.INFO)
                    self.log_console_only(f"📡 Facebook API URL: {post_url}", level=logging.INFO)
                    start_time = time.time()
                    res = self.session.post(post_url, data=data)
                    request_time = time.time() - start_time
                    self.log_console_only(f"⏱️ Facebook API request completed in {request_time:.2f} seconds", level=logging.INFO)
                    self.log_console_only(f"📊 Facebook response status: {res.status_code}", level=logging.INFO)
                    try:
                        response_json = res.json()
                        self.log_console_only(f"📄 Facebook response: {json.dumps(response_json, indent=2)}", level=logging.INFO)
                    except:
                        self.log_console_only(f"📄 Facebook response text: {res.text}", level=logging.INFO)
                    if res.status_code == 200:
                        response_data = res.json()
                        video_id = response_data.get("id", "Unknown")
                        self.send_message(f"✅ Facebook Page post published successfully!\n📘 Video ID: {video_id}\n📘 Page ID: {self.fb_page_id}")
                        self.verify_facebook_post_by_video_id(video_id, page_token)
                        return True
                    else:
                        error_msg = res.json().get("error", {}).get("message", "Unknown error")
                        error_code = res.json().get("error", {}).get("code", "N/A")
                        error_subcode = res.json().get("error", {}).get("error_subcode", "N/A")
                        error_type = res.json().get("error", {}).get("type", "N/A")
                        self.send_message(f"❌ Facebook Page upload failed:", level=logging.ERROR)
                        self.send_message(f"📘 Error: {error_msg}", level=logging.ERROR)
                        self.send_message(f"📘 Code: {error_code}", level=logging.ERROR)
                        self.send_message(f"📘 Subcode: {error_subcode}", level=logging.ERROR)
                        self.send_message(f"📘 Type: {error_type}", level=logging.ERROR)
                        self.send_message(f"📘 Status: {res.status_code}", level=logging.ERROR)
                        self.send_message("⚠️ Facebook upload failed, but Instagram upload was successful", level=logging.WARNING)
                        return False
                except Exception as e:
                    self.send_message(f"❌ Facebook Page upload exception:\n📘 Error: {str(e)}", level=logging.ERROR)
                    self.send_message("⚠️ Facebook upload exception, but Instagram upload was successful", level=logging.WARNING)
                    return False

    def authenticate_dropbox(self):
        """Authenticate with Dropbox and return the client."""
        try:
            access_token = self.refresh_dropbox_token()
            return dropbox.Dropbox(oauth2_access_token=access_token)
        except Exception as e:
            self.send_message(f"❌ Dropbox authentication failed: {str(e)}", level=logging.ERROR)
            raise

    def get_remaining_files_count(self, dbx):
        """Get the count of remaining files in Dropbox folder."""
        try:
            files = self.list_dropbox_files(dbx)
            return len(files)
        except Exception as e:
            self.log_console_only(f"⚠️ Could not count remaining files: {e}", level=logging.WARNING)
            return 0

    def process_files_with_retries(self, dbx, caption, description, max_retries=1):
        files = self.list_dropbox_files(dbx)
        if not files:
            self.log_console_only("📭 No files found in Dropbox folder.", level=logging.INFO)
            return False

        # Process only the first file - no retries
        file = files[0]
        self.log_console_only(f"🎯 Processing single file: {file.name}", level=logging.INFO)
        
        try:
            result = self.post_to_instagram(dbx, file, caption, description)
            if isinstance(result, tuple):
                if len(result) == 4:
                    success, media_type, instagram_success, facebook_success = result
                elif len(result) == 2:
                    success, media_type = result
                    instagram_success = success
                    facebook_success = False
                else:
                    success = result
                    media_type = None
                    instagram_success = success
                    facebook_success = False
            else:
                success = result
                media_type = None
                instagram_success = success
                facebook_success = False
        except Exception as e:
            self.send_message(f"❌ Exception during post for {file.name}: {e}", level=logging.ERROR)
            success = False
            media_type = None
            instagram_success = False
            facebook_success = False

        # Always delete the file after an attempt
        try:
            dbx.files_delete_v2(file.path_lower)
            self.log_console_only(f"🗑️ Deleted file after attempt: {file.name}")
        except Exception as e:
            self.log_console_only(f"⚠️ Failed to delete file {file.name}: {e}", level=logging.WARNING)

        # Get remaining files count
        remaining_files = self.get_remaining_files_count(dbx)

        # Report results for each platform separately
        if instagram_success:
            if media_type == "REELS":
                self.send_message("✅ Successfully posted one reel to Instagram", level=logging.INFO)
            elif media_type == "IMAGE":
                self.send_message("✅ Successfully posted one image to Instagram", level=logging.INFO)
            else:
                self.send_message("✅ Successfully posted to Instagram", level=logging.INFO)
        else:
            self.send_message("❌ Instagram post failed", level=logging.ERROR)
            
        if media_type == "REELS":
            if facebook_success:
                self.send_message("✅ Successfully posted one reel to Facebook Page", level=logging.INFO)
            else:
                self.send_message("❌ Facebook Page post failed", level=logging.ERROR)
        
        # Final summary with remaining files count
        if media_type == "REELS":
            self.log_console_only(f"📊 Final Status: Instagram {'✅' if instagram_success else '❌'} | Facebook {'✅' if facebook_success else '❌'} | 📦 Remaining files: {remaining_files}", level=logging.INFO)
        elif media_type == "IMAGE":
            self.log_console_only(f"📊 Final Status: Instagram {'✅' if instagram_success else '❌'} | Facebook {'✅' if facebook_success else '❌'} (image) | 📦 Remaining files: {remaining_files}", level=logging.INFO)
        else:
            self.log_console_only(f"📊 Final Status: Instagram {'✅' if instagram_success else '❌'} | Facebook N/A | 📦 Remaining files: {remaining_files}", level=logging.INFO)
        
        # Return overall success (Instagram success is primary)
        return instagram_success

    def run(self):
        """Main execution method that orchestrates the posting process."""
        self.log_console_only(f"📡 Run started at: {datetime.now(self.ist).strftime('%Y-%m-%d %H:%M:%S')}", level=logging.INFO)
        
        try:
            # Check token expiry first
            token_valid = self.check_token_expiry()
            if not token_valid:
                self.send_message("❌ Token validation failed. Stopping execution.", level=logging.ERROR)
                return
            
            # List available pages for configuration help
            self.list_available_pages()
            
            # Get caption from config
            caption, description = self.get_caption_from_config()
            
            # Authenticate with Dropbox
            dbx = self.authenticate_dropbox()
            
            # Try posting one file only
            success = self.process_files_with_retries(dbx, caption, description, max_retries=1)
            
            if success:
                self.send_message("🎉 Instagram post completed successfully!", level=logging.INFO)
                self.log_console_only("📊 Summary: Instagram ✅ | Facebook status reported separately above", level=logging.INFO)
            else:
                self.send_message("❌ Instagram post failed.", level=logging.ERROR)
            
        except Exception as e:
            self.send_message(f"❌ Script crashed:\n{str(e)}", level=logging.ERROR)
            raise
        finally:
            # Send token expiry info before completion
            self.send_token_expiry_info()
            duration = time.time() - self.start_time
            self.log_console_only(f"🏁 Run complete in {duration:.1f} seconds", level=logging.INFO)

    def check_token_expiry(self):
        """Check Meta token expiry and send Telegram notification."""
        try:
            self.log_console_only("🔍 Checking token expiry...", level=logging.INFO)
            url = "https://graph.facebook.com/debug_token"
            params = {
                "input_token": self.meta_token,
                "access_token": self.meta_token
            }
            
            res = self.session.get(url, params=params)
            data = res.json()
            
            if "data" in data:
                expires_at = data["data"].get("expires_at")
                is_valid = data["data"].get("is_valid")
                
                if expires_at:
                    dt = datetime.fromtimestamp(expires_at).astimezone(self.ist)
                    self.log_console_only(f"🔐 Token Valid: {is_valid}\n⏳ Expires at: {dt.strftime('%Y-%m-%d %H:%M:%S')}", level=logging.INFO)
                else:
                    self.log_console_only("🔐 Token is long-lived or does not expire.", level=logging.INFO)
                
                return is_valid
            else:
                self.send_message(f"⚠️ Token debug info not returned properly: {res.text}", level=logging.WARNING)
                return False
                
        except Exception as e:
            self.send_message(f"⚠️ Token expiry check failed: {str(e)}", level=logging.ERROR)
            return False

    def check_page_permissions(self, page_token):
        """Check what permissions the page access token has."""
        try:
            self.log_console_only("🔍 Checking page permissions...", level=logging.INFO)
            url = f"https://graph.facebook.com/v18.0/me/permissions"
            params = {"access_token": page_token}
            
            self.log_console_only(f"📡 Permission check URL: {url}", level=logging.INFO)
            
            res = self.session.get(url, params=params)
            self.log_console_only(f"📊 Permission check response status: {res.status_code}", level=logging.INFO)
            
            if res.status_code == 200:
                permissions = res.json().get("data", [])
                self.log_console_only(f"📋 Found {len(permissions)} permissions:", level=logging.INFO)
                
                for perm in permissions:
                    permission_name = perm.get("permission", "Unknown")
                    status = perm.get("status", "Unknown")
                    self.log_console_only(f"🔑 {permission_name}: {status}", level=logging.INFO)
                
                # Check for specific permissions needed for video upload
                has_publish_video = any(p.get("permission") == "publish_video" and p.get("status") == "granted" for p in permissions)
                has_publish_actions = any(p.get("permission") == "publish_actions" and p.get("status") == "granted" for p in permissions)
                has_manage_pages = any(p.get("permission") == "manage_pages" and p.get("status") == "granted" for p in permissions)
                has_pages_show_list = any(p.get("permission") == "pages_show_list" and p.get("status") == "granted" for p in permissions)
                
                self.log_console_only("📊 Permission Analysis:", level=logging.INFO)
                self.log_console_only(f"   🎥 publish_video: {'✅' if has_publish_video else '❌'}", level=logging.INFO)
                self.log_console_only(f"   📝 publish_actions: {'✅' if has_publish_actions else '❌'}", level=logging.INFO)
                self.log_console_only(f"   ⚙️ manage_pages: {'✅' if has_manage_pages else '❌'}", level=logging.INFO)
                self.log_console_only(f"   📋 pages_show_list: {'✅' if has_pages_show_list else '❌'}", level=logging.INFO)
                
                if not has_publish_video:
                    self.send_message("⚠️ Missing 'publish_video' permission! This is required for video uploads.", level=logging.WARNING)
                if not has_publish_actions:
                    self.send_message("⚠️ Missing 'publish_actions' permission! This is required for content publishing.", level=logging.WARNING)
                if not has_manage_pages:
                    self.send_message("⚠️ Missing 'manage_pages' permission! This is required for page management.", level=logging.WARNING)
                
                # For Facebook video uploads, we need publish_video
                if has_publish_video and has_publish_actions:
                    self.log_console_only("✅ Page has all required permissions for video publishing!", level=logging.INFO)
                    return True
                else:
                    self.send_message("❌ Page missing required permissions for video publishing", level=logging.ERROR)
                    return False
            else:
                error_response = res.text
                self.send_message(f"❌ Failed to check permissions: {res.status_code}", level=logging.ERROR)
                self.log_console_only(f"📄 Error response: {error_response}", level=logging.INFO)
                
                # If permission check fails, let's try a different approach
                self.log_console_only("🔄 Trying alternative permission check...", level=logging.INFO)
                return self.check_page_permissions_alternative(page_token)
                
        except Exception as e:
            self.send_message(f"❌ Exception checking permissions: {e}", level=logging.ERROR)
            return False

    def check_page_permissions_alternative(self, page_token):
        """Alternative method to check page permissions using page info."""
        try:
            self.log_console_only("🔍 Alternative permission check using page info...", level=logging.INFO)
            
            # Try to get page info and check if it has video publishing capabilities
            url = f"https://graph.facebook.com/v18.0/{self.fb_page_id}"
            params = {
                "fields": "id,name,category,fan_count,verification_status,connected_instagram_account",
                "access_token": page_token
            }
            
            self.log_console_only(f"📡 Alternative check URL: {url}", level=logging.INFO)
            
            res = self.session.get(url, params=params)
            if res.status_code == 200:
                page_info = res.json()
                page_name = page_info.get("name", "Unknown")
                page_category = page_info.get("category", "Unknown")
                
                self.log_console_only(f"✅ Alternative check successful!", level=logging.INFO)
                self.log_console_only(f"📄 Page Name: {page_name}", level=logging.INFO)
                self.log_console_only(f"📄 Page Category: {page_category}", level=logging.INFO)
                
                # Since we can access the page info, the token has basic permissions
                # Let's assume it can publish videos (we'll find out when we try)
                self.log_console_only("✅ Assuming page has video publishing permissions (will test during upload)", level=logging.INFO)
                return True
            else:
                self.send_message(f"❌ Alternative check also failed: {res.status_code}", level=logging.ERROR)
                return False
                
        except Exception as e:
            self.send_message(f"❌ Exception in alternative permission check: {e}", level=logging.ERROR)
            return False

    def refresh_page_access_token(self, page_token):
        """Refresh the page access token if it's expired."""
        try:
            self.log_console_only("🔄 Refreshing page access token...", level=logging.INFO)
            url = f"https://graph.facebook.com/v18.0/oauth/access_token"
            params = {
                "grant_type": "fb_exchange_token",
                "client_id": self.dropbox_key,  # Using app ID
                "client_secret": self.dropbox_secret,  # Using app secret
                "fb_exchange_token": page_token
            }
            
            res = self.session.get(url, params=params)
            if res.status_code == 200:
                new_token = res.json().get("access_token")
                expires_in = res.json().get("expires_in", "Unknown")
                self.send_message(f"✅ Page access token refreshed successfully! Expires in: {expires_in} seconds")
                return new_token
            else:
                self.send_message(f"❌ Failed to refresh page token: {res.text}", level=logging.ERROR)
                return None
        except Exception as e:
            self.send_message(f"❌ Exception refreshing page token: {e}", level=logging.ERROR)
            return None

    def list_available_pages(self):
        """List all available pages for the user to help with configuration."""
        try:
            self.log_console_only("🔍 Listing all available pages for configuration...", level=logging.INFO)
            url = f"https://graph.facebook.com/v18.0/me/accounts"
            params = {"access_token": self.meta_token}
            
            res = self.session.get(url, params=params)
            if res.status_code != 200:
                self.send_message(f"❌ Failed to fetch pages: {res.text}", level=logging.ERROR)
                return

            pages = res.json().get("data", [])
            self.log_console_only(f"📋 Found {len(pages)} pages:", level=logging.INFO)
            
            for i, page in enumerate(pages):
                page_id = page.get("id", "Unknown")
                page_name = page.get("name", "Unknown")
                category = page.get("category", "Unknown")
                tasks = page.get("tasks", [])
                
                self.log_console_only(f"📄 Page {i+1}:", level=logging.INFO)
                self.log_console_only(f"   📝 Name: {page_name}", level=logging.INFO)
                self.log_console_only(f"   🆔 ID: {page_id}", level=logging.INFO)
                self.log_console_only(f"   📂 Category: {category}", level=logging.INFO)
                self.log_console_only(f"   🔧 Tasks: {', '.join(tasks)}", level=logging.INFO)
                
                # Check if this matches current configuration
                if page_id == self.fb_page_id:
                    self.log_console_only(f"   ✅ CURRENTLY CONFIGURED", level=logging.INFO)
                else:
                    self.log_console_only(f"   ⚙️ To use this page, set FB_PAGE_ID={page_id}", level=logging.INFO)
            
            self.log_console_only("💡 Copy the ID of the page you want to use and set it as FB_PAGE_ID environment variable.", level=logging.INFO)
            
        except Exception as e:
            self.send_message(f"❌ Exception listing pages: {e}", level=logging.ERROR)

    def exchange_user_token_for_page_token(self, page_id):
        """Exchange user access token for page access token."""
        try:
            self.send_message(f"🔄 Exchanging token for page ID: {page_id}", level=logging.INFO)
            
            # Use the page token endpoint to get the actual page access token
            # This is the correct way to get a page access token
            url = f"https://graph.facebook.com/v18.0/{page_id}"
            params = {
                "fields": "access_token",
                "access_token": self.meta_token
            }
            
            self.send_message(f"📡 Exchange API URL: {url}", level=logging.INFO)
            self.send_message(f"🔑 Using user token to get page token for page: {page_id}", level=logging.INFO)
            
            start_time = time.time()
            res = self.session.get(url, params=params)
            request_time = time.time() - start_time
            
            self.send_message(f"⏱️ Token exchange completed in {request_time:.2f} seconds", level=logging.INFO)
            self.send_message(f"📊 Exchange response status: {res.status_code}", level=logging.INFO)
            
            if res.status_code == 200:
                response_data = res.json()
                page_token = response_data.get("access_token")
                
                if page_token:
                    self.send_message("✅ Page access token obtained successfully!")
                    self.send_message(f"🔐 Page token starts with: {page_token[:20]}...", level=logging.INFO)
                    return page_token
                else:
                    self.send_message("❌ No access_token in response", level=logging.ERROR)
                    self.send_message(f"📄 Response data: {response_data}", level=logging.ERROR)
                    return None
            else:
                self.send_message(f"❌ Token exchange failed: {res.text}", level=logging.ERROR)
                return None
                
        except Exception as e:
            self.send_message(f"❌ Exception during token exchange: {e}", level=logging.ERROR)
            return None

    def check_instagram_page_connection(self, page_token):
        """Check if Instagram account is properly connected to the Facebook page."""
        try:
            self.log_console_only("🔍 Checking Instagram-Facebook page connection...", level=logging.INFO)
            
            # Check if the page has Instagram account connected
            url = f"https://graph.facebook.com/v18.0/{self.fb_page_id}"
            params = {
                "fields": "instagram_business_account,connected_instagram_account",
                "access_token": page_token
            }
            
            self.log_console_only(f"📡 Checking page Instagram connection: {url}", level=logging.INFO)
            
            res = self.session.get(url, params=params)
            if res.status_code == 200:
                data = res.json()
                instagram_business_account = data.get("instagram_business_account", {})
                connected_instagram = data.get("connected_instagram_account", {})
                
                if instagram_business_account:
                    instagram_id = instagram_business_account.get("id", "Unknown")
                    self.send_message(f"✅ Instagram Business Account connected: {instagram_id}", level=logging.INFO)
                    
                    # Verify this matches our configured IG_ID
                    if instagram_id == self.ig_id:
                        self.log_console_only("✅ Instagram ID matches configured IG_ID", level=logging.INFO)
                        return True
                    else:
                        self.send_message(f"⚠️ Instagram ID mismatch! Configured: {self.ig_id}, Connected: {instagram_id}", level=logging.WARNING)
                        return False
                elif connected_instagram:
                    instagram_id = connected_instagram.get("id", "Unknown")
                    self.send_message(f"✅ Instagram Account connected: {instagram_id}", level=logging.INFO)
                    return True
                else:
                    self.send_message("❌ No Instagram account connected to this Facebook page!", level=logging.ERROR)
                    return False
            else:
                self.send_message(f"❌ Failed to check Instagram connection: {res.text}", level=logging.ERROR)
                return False
                
        except Exception as e:
            self.send_message(f"❌ Exception checking Instagram connection: {e}", level=logging.ERROR)
            return False

    def test_page_token(self, page_token):
        """Test the page access token by making a simple API call."""
        try:
            self.log_console_only("🧪 Testing page access token...", level=logging.INFO)
            
            # Test the token by getting page info
            url = f"https://graph.facebook.com/v18.0/me"
            params = {
                "fields": "id,name,category",
                "access_token": page_token
            }
            
            self.log_console_only(f"📡 Testing token with: {url}", level=logging.INFO)
            
            start_time = time.time()
            res = self.session.get(url, params=params)
            request_time = time.time() - start_time
            
            self.log_console_only(f"⏱️ Token test completed in {request_time:.2f} seconds", level=logging.INFO)
            self.log_console_only(f"📊 Test response status: {res.status_code}", level=logging.INFO)
            
            if res.status_code == 200:
                page_info = res.json()
                page_id = page_info.get("id", "Unknown")
                page_name = page_info.get("name", "Unknown")
                page_category = page_info.get("category", "Unknown")
                
                self.log_console_only(f"✅ Page token test successful!", level=logging.INFO)
                self.log_console_only(f"📄 Page ID: {page_id}", level=logging.INFO)
                self.log_console_only(f"📄 Page Name: {page_name}", level=logging.INFO)
                self.log_console_only(f"📄 Page Category: {page_category}", level=logging.INFO)
                
                # Verify this matches our expected page
                if page_id == self.fb_page_id:
                    self.log_console_only("✅ Page ID matches expected page!", level=logging.INFO)
                    return True
                else:
                    self.send_message(f"⚠️ Page ID mismatch! Expected: {self.fb_page_id}, Got: {page_id}", level=logging.WARNING)
                    return False
            else:
                self.send_message(f"❌ Page token test failed: {res.text}", level=logging.ERROR)
                return False
                
        except Exception as e:
            self.send_message(f"❌ Exception testing page token: {e}", level=logging.ERROR)
            return False

    def verify_token_type(self, page_token):
        """Verify if the token is a page token."""
        try:
            self.send_message("🔍 Verifying token type...", level=logging.INFO)
            
            # Check if the token is valid by making a simple API call
            url = f"https://graph.facebook.com/v18.0/me"
            params = {
                "fields": "id,name,category",
                "access_token": page_token
            }
            
            self.send_message(f"📡 Verification URL: {url}", level=logging.INFO)
            
            start_time = time.time()
            res = self.session.get(url, params=params)
            request_time = time.time() - start_time
            
            self.send_message(f"⏱️ Verification completed in {request_time:.2f} seconds", level=logging.INFO)
            self.send_message(f"📊 Verification response status: {res.status_code}", level=logging.INFO)
            
            if res.status_code == 200:
                page_info = res.json()
                page_id = page_info.get("id", "Unknown")
                page_name = page_info.get("name", "Unknown")
                page_category = page_info.get("category", "Unknown")
                
                self.send_message(f"✅ Token verification successful!", level=logging.INFO)
                self.send_message(f"📄 Page ID: {page_id}", level=logging.INFO)
                self.send_message(f"📄 Page Name: {page_name}", level=logging.INFO)
                self.send_message(f"📄 Page Category: {page_category}", level=logging.INFO)
                
                # Verify this matches our expected page
                if page_id == self.fb_page_id:
                    self.send_message("✅ Page ID matches expected page!", level=logging.INFO)
                    return True
                else:
                    self.send_message(f"⚠️ Page ID mismatch! Expected: {self.fb_page_id}, Got: {page_id}", level=logging.WARNING)
                    return False
            else:
                self.send_message(f"❌ Token verification failed: {res.text}", level=logging.ERROR)
                return False
                
        except Exception as e:
            self.send_message(f"❌ Exception verifying token type: {e}", level=logging.ERROR)
            return False

    def verify_instagram_post_by_media_id(self, media_id, page_token):
        """Verify Instagram post is live by polling the published media_id."""
        try:
            self.send_message("🔍 Verifying Instagram post is live...", level=logging.INFO)
            
            # Poll the media_id to get post details
            url = f"{self.INSTAGRAM_API_BASE}/{media_id}"
            params = {
                "fields": "id,permalink_url,media_type,media_url,thumbnail_url,created_time",
                "access_token": page_token
            }
            
            self.log_console_only(f"📡 Verification URL: {url}", level=logging.INFO)
            
            # Try up to 10 times with 5-second intervals (increased from 5 attempts, 3 seconds)
            for attempt in range(10):
                self.log_console_only(f"🔄 Verification attempt {attempt + 1}/10", level=logging.INFO)
                
                res = self.session.get(url, params=params)
                if res.status_code == 200:
                    post_data = res.json()
                    post_id = post_data.get("id", "Unknown")
                    permalink = post_data.get("permalink_url", "Not available")
                    media_type = post_data.get("media_type", "Unknown")
                    created_time = post_data.get("created_time", "Unknown")
                    
                    self.send_message(f"✅ Instagram post verified as live!", level=logging.INFO)
                    self.log_console_only(f"📸 Post ID: {post_id}", level=logging.INFO)
                    self.log_console_only(f"🔗 Permalink: {permalink}", level=logging.INFO)
                    self.log_console_only(f"📂 Media Type: {media_type}", level=logging.INFO)
                    self.log_console_only(f"⏰ Created: {created_time}", level=logging.INFO)
                    return True
                elif res.status_code == 400:
                    self.send_message("⚠️ Permanent error on verification (400 Bad Request), stopping early.", level=logging.WARNING)
                    self.log_console_only(f"❌ Unrecoverable error on attempt {attempt + 1}: {res.status_code}", level=logging.INFO)
                    break
                else:
                    self.log_console_only(f"❌ Verification failed (attempt {attempt + 1}): {res.status_code}", level=logging.INFO)
                    if attempt < 9:  # Don't sleep on last attempt
                        time.sleep(5)  # Increased from 3 seconds
            
            self.send_message("⚠️ Could not verify Instagram post is live after 10 attempts", level=logging.WARNING)
            return False
            
        except Exception as e:
            self.send_message(f"❌ Exception verifying Instagram post: {e}", level=logging.ERROR)
            return False

    def verify_facebook_post_by_video_id(self, video_id, page_token):
        """Verify Facebook video post is live by polling the video_id."""
        try:
            self.send_message("🔍 Verifying Facebook video post is live...", level=logging.INFO)
            
            # Poll the video_id to get post details
            url = f"https://graph.facebook.com/{video_id}"
            params = {
                "fields": "id,permalink_url,created_time,length,title,description",
                "access_token": page_token
            }
            
            self.log_console_only(f"📡 Verification URL: {url}", level=logging.INFO)
            
            # Try up to 10 times with 5-second intervals (increased from 5 attempts, 3 seconds)
            for attempt in range(10):
                self.log_console_only(f"🔄 Verification attempt {attempt + 1}/10", level=logging.INFO)
                
                res = self.session.get(url, params=params)
                if res.status_code == 200:
                    post_data = res.json()
                    fb_video_id = post_data.get("id", "Unknown")
                    permalink = post_data.get("permalink_url", "Not available")
                    created_time = post_data.get("created_time", "Unknown")
                    length = post_data.get("length", "Unknown")
                    
                    self.send_message(f"✅ Facebook video post verified as live!", level=logging.INFO)
                    self.log_console_only(f"📘 Video ID: {fb_video_id}", level=logging.INFO)
                    self.log_console_only(f"🔗 Permalink: {permalink}", level=logging.INFO)
                    self.log_console_only(f"⏰ Created: {created_time}", level=logging.INFO)
                    self.log_console_only(f"⏱️ Length: {length} seconds", level=logging.INFO)
                    return True
                elif res.status_code == 400:
                    self.send_message("⚠️ Permanent error on Facebook verification (400 Bad Request), stopping early.", level=logging.WARNING)
                    self.log_console_only(f"❌ Unrecoverable error on attempt {attempt + 1}: {res.status_code}", level=logging.INFO)
                    break
                else:
                    self.log_console_only(f"❌ Verification failed (attempt {attempt + 1}): {res.status_code}", level=logging.INFO)
                    if attempt < 9:  # Don't sleep on last attempt
                        time.sleep(5)  # Increased from 3 seconds
            
            self.send_message("⚠️ Could not verify Facebook video post is live after 10 attempts", level=logging.WARNING)
            return False
            
        except Exception as e:
            self.send_message(f"❌ Exception verifying Facebook video post: {e}", level=logging.ERROR)
            return False

if __name__ == "__main__":
    DropboxToInstagramUploader().run()
