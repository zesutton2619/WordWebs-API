import json
import urllib.request
import urllib.parse
import base64
import uuid
import os
from typing import Optional, Dict, Any


def send_discord_message_with_image(channel_id: str, content: str, image_bytes: bytes, bot_token: str) -> Optional[str]:
    """
    Send message with image attachment to Discord channel using bot token
    Returns Discord message ID if successful, None if failed
    """
    try:
        print(f"Building multipart request for channel {channel_id}")
        
        # Create multipart form data
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        print(f"Using boundary: {boundary}")
        
        # Build multipart body
        body_parts = []
        
        # Add content as payload_json
        payload = {
            "content": content
        }
        
        body_parts.append(f'--{boundary}')
        body_parts.append('Content-Disposition: form-data; name="payload_json"')
        body_parts.append('Content-Type: application/json')
        body_parts.append('')
        body_parts.append(json.dumps(payload))
        
        # Add image file
        body_parts.append(f'--{boundary}')
        body_parts.append('Content-Disposition: form-data; name="files[0]"; filename="wordwebs-state.png"')
        body_parts.append('Content-Type: image/png')
        body_parts.append('')
        
        # Join text parts and encode
        text_body = '\r\n'.join(body_parts) + '\r\n'
        text_body_bytes = text_body.encode('utf-8')
        
        # Add image bytes
        closing_boundary = f'\r\n--{boundary}--\r\n'.encode('utf-8')
        
        # Combine all parts
        full_body = text_body_bytes + image_bytes + closing_boundary
        
        print(f"Request body size: {len(full_body)} bytes")
        
        # Send request to Discord
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        print(f"Sending request to: {url}")
        
        headers = {
            'Authorization': f'Bot {bot_token}',
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'User-Agent': f'WordWebs-Bot/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})'
        }
        
        req = urllib.request.Request(url, data=full_body, headers=headers)
        
        print("Making request to Discord API...")
        
        with urllib.request.urlopen(req) as response:
            print(f"Discord API response status: {response.status}")
            if response.status == 200 or response.status == 201:
                response_body = response.read().decode('utf-8')
                response_data = json.loads(response_body)
                print(f"Discord API success response: {response_body}")
                return response_data.get('id')  # Return Discord message ID
            else:
                error_body = response.read().decode('utf-8')
                print(f"Discord API error {response.status}: {error_body}")
                return None
                
    except Exception as e:
        print(f"Error sending Discord message with image: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return None


def edit_discord_message_with_image(channel_id: str, message_id: str, content: str, image_bytes: bytes, bot_token: str) -> Optional[str]:
    """
    Edit existing Discord message with new content and image
    For now, just delete the old message and create a new one since PATCH with files is complex
    Returns new message ID if successful, None if failed
    """
    try:
        print(f"Editing Discord message {message_id} in channel {channel_id}")
        print("Note: Due to Discord API limitations, deleting old message and creating new one")
        
        # Delete the old message first
        delete_url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
        delete_headers = {
            'Authorization': f'Bot {bot_token}',
            'User-Agent': f'WordWebs-Bot/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})'
        }
        
        delete_req = urllib.request.Request(delete_url, headers=delete_headers)
        delete_req.get_method = lambda: 'DELETE'
        
        try:
            with urllib.request.urlopen(delete_req) as delete_response:
                print(f"Delete response status: {delete_response.status}")
        except Exception as delete_error:
            print(f"Error deleting message (continuing anyway): {delete_error}")
        
        # Create new message (reuse the existing function)
        new_message_id = send_discord_message_with_image(channel_id, content, image_bytes, bot_token)
        
        if new_message_id:
            print(f"Successfully created new message: {new_message_id}")
            return new_message_id
        else:
            print("Failed to create new message")
            return None
                
    except Exception as e:
        print(f"Error editing Discord message: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return None


def generate_game_state_message(game_state: Dict[str, Any], player_info: Dict[str, Any], puzzle_number: int) -> str:
    """Generate Discord message content based on game state"""
    username = player_info.get('username', 'Player')
    solved_groups = len(game_state.get('solved_groups', []))
    attempts_remaining = game_state.get('attempts_remaining', 4)
    
    if solved_groups == 4:
        return f"🎉 {username} completed today's Word Webs #{puzzle_number}!"
    elif attempts_remaining == 0 and solved_groups < 4:
        return f"💔 {username} ran out of attempts on Word Webs #{puzzle_number}"
    elif attempts_remaining == 1:
        return f"⚠️ {username} has {solved_groups}/4 groups in Word Webs #{puzzle_number} (1 attempt remaining!)"
    else:
        return f"{username} has {solved_groups}/4 groups in Word Webs #{puzzle_number} ({attempts_remaining} attempts remaining)"


def get_channel_from_context(discord_sdk_context: Optional[Dict]) -> Optional[str]:
    """Extract channel ID from Discord SDK context"""
    if not discord_sdk_context:
        return None
    
    # Try to get channel ID from various Discord context sources
    channel_id = discord_sdk_context.get('channel_id')
    if not channel_id:
        # Fallback to other possible locations in Discord context
        channel_id = discord_sdk_context.get('channelId')
    
    return channel_id