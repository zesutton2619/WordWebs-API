import sys
import os
sys.path.append('/opt')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import json
import urllib.request
from datetime import datetime, timedelta
import pytz
from shared.dynamodb_client import DynamoDBClient
from game_state_image_generator import generate_combined_summary_image


def lambda_handler(event, context):
    """
    Scheduled Lambda function to send daily WordWebs summaries to Discord channels
    Triggered daily at 12:05 AM EST (5 minutes after new puzzle generation)
    """
    
    try:
        print("Starting daily summary sender...")
        
        # Get yesterday's date in EST
        est = pytz.timezone('US/Eastern')
        yesterday = datetime.now(est) - timedelta(days=1)
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        
        print(f"Sending summaries for date: {yesterday_str}")
        
        db = DynamoDBClient()
        
        # Get all active Discord channels
        active_channels = db.get_active_discord_channels()
        
        if not active_channels:
            print("No active Discord channels found")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No active channels found'
                })
            }
        
        print(f"Sending summaries to {len(active_channels)} channels")
        
        # Send summary to each active channel with per-channel stats
        sent_count = 0
        failed_count = 0
        
        for channel in active_channels:
            try:
                channel_id = channel['channel_id']
                
                # Get games for this specific channel only
                channel_games = db.get_all_daily_games(yesterday_str, channel_id)
                
                if not channel_games or len(channel_games) == 0:
                    print(f"No players found for {yesterday_str} in channel {channel_id}, skipping")
                    continue
                
                print(f"Found {len(channel_games)} players for {yesterday_str} in channel {channel_id}")
                
                # Calculate puzzle number
                puzzle_number = calculate_puzzle_number(yesterday_str)
                
                # Get detailed player data for image generation (channel-specific)
                detailed_players_data = get_detailed_players_data(db, channel_games, yesterday_str)
                print(f"Retrieved detailed data for {len(detailed_players_data)} players in channel {channel_id}")
                
                # Generate combined summary image (channel-specific)
                try:
                    summary_image_bytes = generate_combined_summary_image(detailed_players_data, puzzle_number, yesterday_str)
                    print(f"Generated summary image: {len(summary_image_bytes)} bytes for channel {channel_id}")
                except Exception as e:
                    print(f"Failed to generate summary image for channel {channel_id}: {str(e)}")
                    summary_image_bytes = None
                
                success = send_discord_summary(
                    channel_id=channel_id,
                    guild_id=channel.get('guild_id'),
                    leaderboard=channel_games,
                    puzzle_number=puzzle_number,
                    date=yesterday_str,
                    bot_token=None,  # Remove bot_token usage
                    summary_image_bytes=summary_image_bytes
                )
                
                if success:
                    sent_count += 1
                    print(f"Sent summary to channel {channel_id}")
                else:
                    failed_count += 1
                    print(f"Failed to send summary to channel {channel_id}")
                    
            except Exception as e:
                failed_count += 1
                print(f"Error sending to channel {channel.get('channel_id', 'unknown')}: {str(e)}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Daily summaries sent',
                'date': yesterday_str,
                'channels_sent': sent_count,
                'channels_failed': failed_count,
                'puzzle_number': puzzle_number
            })
        }
        
    except Exception as e:
        print(f"Error in daily summary sender: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Failed to send daily summaries: {str(e)}'
            })
        }


def send_discord_summary(channel_id, guild_id, leaderboard, puzzle_number, date, bot_token=None, summary_image_bytes=None):
    """
    Send summary message to Discord channel using bot token with optional image
    """
    try:
        # Use global bot token (remove per-server bot token feature)
        bot_token = os.environ.get('DISCORD_BOT_TOKEN')
        
        if not bot_token:
            print("No Discord bot token available")
            return False
        
        # Create summary message content
        content = create_summary_message(leaderboard, puzzle_number, date)
        
        # Send message via Discord Bot API
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        
        # Create Activity invite link
        activity_invite = None
        if bot_token:
            activity_invite = create_activity_invite(channel_id, bot_token)
        
        if summary_image_bytes:
            # Send with image attachment using multipart form data
            message_id = send_discord_message_with_image(url, bot_token, content, leaderboard, puzzle_number, date, summary_image_bytes, channel_id, guild_id)
        else:
            # Send text-only message (fallback)
            payload = {
                "content": content,
                "embeds": [create_summary_embed(leaderboard, puzzle_number, date)]
            }
            
            headers = {
                'Authorization': f'Bot {bot_token}',
                'Content-Type': 'application/json',
                'User-Agent': f'WordWebs-Bot/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})'
            }
            
            req_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=req_data, headers=headers)
            
            with urllib.request.urlopen(req) as response:
                if response.status == 200 or response.status == 201:
                    response_data = json.loads(response.read().decode('utf-8'))
                    message_id = response_data.get('id')
                else:
                    print(f"Discord API returned status {response.status}")
                    message_id = None
        
        # If we got a message ID and activity invite, edit the message to add the Play Now button
        if message_id and activity_invite:
            return edit_message_with_play_button(channel_id, message_id, bot_token, content, leaderboard, puzzle_number, date, activity_invite)
        
        return message_id is not None
                
    except Exception as e:
        print(f"Error sending Discord message: {str(e)}")
        return False


def send_discord_message_with_image(url, bot_token, content, leaderboard, puzzle_number, date, image_bytes, channel_id=None, guild_id=None):
    """
    Send Discord message with image attachment using multipart form data
    """
    import uuid
    
    try:
        # Create Activity invite link
        activity_invite = None
        if bot_token:
            activity_invite = create_activity_invite(channel_id, bot_token)
        
        # Create multipart boundary
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        
        # Create multipart form data
        form_data = []
        
        # Add JSON payload with action row for Play Now button
        payload = {
            "content": content,
            "embeds": [create_summary_embed(leaderboard, puzzle_number, date)]
        }
        
        # Don't add Play Now button initially - we'll add it in the edit step
        
        form_data.append(f'--{boundary}'.encode())
        form_data.append(b'Content-Disposition: form-data; name="payload_json"')
        form_data.append(b'Content-Type: application/json')
        form_data.append(b'')
        form_data.append(json.dumps(payload).encode('utf-8'))
        
        # Add image file
        form_data.append(f'--{boundary}'.encode())
        form_data.append(b'Content-Disposition: form-data; name="files[0]"; filename="wordwebs_summary.png"')
        form_data.append(b'Content-Type: image/png')
        form_data.append(b'')
        form_data.append(image_bytes)
        
        # Close boundary
        form_data.append(f'--{boundary}--'.encode())
        
        # Join form data
        body = b'\r\n'.join(form_data)
        
        # Create request
        headers = {
            'Authorization': f'Bot {bot_token}',
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'User-Agent': f'WordWebs-Bot/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})'
        }
        
        req = urllib.request.Request(url, data=body, headers=headers)
        
        with urllib.request.urlopen(req) as response:
            if response.status == 200 or response.status == 201:
                response_data = json.loads(response.read().decode('utf-8'))
                message_id = response_data.get('id')
                print(f"Successfully sent Discord message with image, message ID: {message_id}")
                return message_id
            else:
                print(f"Discord API returned status {response.status}")
                response_body = response.read().decode('utf-8')
                print(f"Response body: {response_body}")
                return None
                
    except Exception as e:
        print(f"Error sending Discord message with image: {str(e)}")
        return None


def edit_message_with_play_button(channel_id, message_id, bot_token, content, leaderboard, puzzle_number, date, activity_invite):
    """
    Edit the Discord message to add the Play Now button with the correct message link
    """
    try:
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
        
        payload = {
            "content": content,
            "embeds": [create_summary_embed(leaderboard, puzzle_number, date)],
            "components": [{
                "type": 1,  # Action Row
                "components": [{
                    "type": 2,  # Button
                    "style": 5,  # Link button (external)
                    "label": "🎮 Play Now",
                    "url": activity_invite
                }]
            }]
        }
        
        headers = {
            'Authorization': f'Bot {bot_token}',
            'Content-Type': 'application/json',
            'User-Agent': f'WordWebs-Bot/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})'
        }
        
        req_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=req_data, headers=headers, method='PATCH')
        
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                print(f"Successfully edited message {message_id} with Play Now button")
                return True
            else:
                print(f"Failed to edit message: {response.status}")
                response_body = response.read().decode('utf-8')
                print(f"Response body: {response_body}")
                return False
                
    except Exception as e:
        print(f"Error editing Discord message: {str(e)}")
        return False


def create_activity_invite(channel_id, bot_token):
    """Create an invite link for the Discord Activity"""
    try:
        client_id = os.environ.get('DISCORD_CLIENT_ID')
        if not client_id:
            print("DISCORD_CLIENT_ID not found in environment")
            return None
            
        # Create invite for Activity
        url = f"https://discord.com/api/v10/channels/{channel_id}/invites"
        
        payload = {
            "max_age": 86400,  # 24 hours
            "max_uses": 0,     # Unlimited uses
            "target_type": 2,  # EMBEDDED_APPLICATION
            "target_application_id": client_id
        }
        
        headers = {
            'Authorization': f'Bot {bot_token}',
            'Content-Type': 'application/json',
            'User-Agent': f'WordWebs-Bot/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})'
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                invite_data = json.loads(response.read().decode('utf-8'))
                invite_code = invite_data.get('code')
                if invite_code:
                    print(f"Created Activity invite: https://discord.gg/{invite_code}")
                    return f"https://discord.gg/{invite_code}"
                    
        print(f"Failed to create invite: {response.status}")
        response_body = response.read().decode('utf-8')
        print(f"Response body: {response_body}")
        return None
        
    except Exception as e:
        print(f"Error creating Activity invite: {str(e)}")
        return None


def create_summary_message(games, puzzle_number, date):
    """Create a simplified main text content for the summary message"""
    
    content = f"📊 **WordWebs #{puzzle_number} Daily Results**\n"
    
    if len(games) == 0:
        content += "No one played yesterday's puzzle! 🤔"
    else:
        completed_games = [g for g in games if g.get('completed', False)]
        incomplete_games = [g for g in games if not g.get('completed', False)]
        
        # Mention completed players
        if completed_games:
            mentions = [f"<@{player['discord_id']}>" for player in completed_games[:5]]
            if len(completed_games) > 5:
                content += f"🎉 {', '.join(mentions)} and {len(completed_games) - 5} others completed the puzzle!"
            else:
                content += f"🎉 {', '.join(mentions)} completed the puzzle!"
        
        # Mention incomplete players (if no completed ones)
        elif incomplete_games:
            mentions = [f"<@{player['discord_id']}>" for player in incomplete_games[:5]]
            if len(incomplete_games) > 5:
                content += f"🎮 {', '.join(mentions)} and {len(incomplete_games) - 5} others tried the puzzle!"
            else:
                content += f"🎮 {', '.join(mentions)} tried the puzzle!"
    
    return content


def create_summary_embed(games, puzzle_number, date):
    """Create a Discord embed with visual summary"""
    
    embed = {
        "title": f"WordWebs #{puzzle_number} Results",
        "description": f"Daily summary for {date}",
        "color": 0x9333ea,  # Purple to match frontend
        "fields": [],
        "footer": {
            "text": "WordWebs - Daily Word Puzzle Game"
        },
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if games:
        completed_games = [g for g in games if g.get('completed', False)]
        incomplete_games = [g for g in games if not g.get('completed', False)]
        
        # Add participation stats
        embed["fields"].append({
            "name": "📈 Participation",
            "value": f"**{len(games)}** players participated\n**{len(completed_games)}** completed\n**{len(incomplete_games)}** attempted",
            "inline": True
        })
        
        # Add fastest time if anyone completed
        if completed_games and completed_games[0].get('completion_time'):
            fastest_time = format_completion_time(completed_games[0]['completion_time'])
            embed["fields"].append({
                "name": "⚡ Fastest Completion",
                "value": f"<@{completed_games[0]['discord_id']}>\n{fastest_time}",
                "inline": True
            })
        
        # Add attempt summary for incomplete games
        if incomplete_games:
            best_incomplete = max(incomplete_games, key=lambda x: x.get('solved_groups_count', 0))
            embed["fields"].append({
                "name": "🎯 Best Attempt",
                "value": f"<@{best_incomplete['discord_id']}>\n{best_incomplete.get('solved_groups_count', 0)}/4 groups solved",
                "inline": True
            })
    
    return embed


def calculate_puzzle_number(date_str):
    """Calculate puzzle number based on date (days since launch)"""
    # Match frontend launch date (2025-07-30)
    launch_date = datetime.strptime('2025-07-30', '%Y-%m-%d')
    puzzle_date = datetime.strptime(date_str, '%Y-%m-%d')
    
    diff_days = (puzzle_date - launch_date).days
    return max(1, diff_days + 1)


def get_detailed_players_data(db, games, date):
    """
    Get detailed player data including game sessions and Discord avatars
    """
    detailed_players = []
    
    for player in games:
        try:
            display_name = player['display_name']
            discord_id = player['discord_id']  # Already available in the new format
            
            # Get the full game session to get solved_groups and guesses
            session = db.get_user_game_session(discord_id, date)
            if not session:
                print(f"Could not find session for {display_name}")
                continue
            
            # Get Discord avatar URL
            avatar_url = get_discord_avatar_url(discord_id)
            
            # Prepare player data for image generation
            player_data = {
                'display_name': display_name,
                'discord_id': discord_id,
                'avatar_url': avatar_url,
                'solved_groups': session.get('solved_groups', []),
                'guesses': session.get('guesses', []),
                'attempts_remaining': session.get('attempts_remaining', 0),
                'completion_time': session.get('completion_time', 0),
                'completed': player.get('completed', False),
                'rank': player.get('rank', 0),
                'solved_groups_count': player.get('solved_groups_count', 0),
                'attempts_used': player.get('attempts_used', 0)
            }
            
            detailed_players.append(player_data)
            
        except Exception as e:
            print(f"Error getting detailed data for player {player.get('display_name', 'unknown')}: {str(e)}")
            continue
    
    return detailed_players


def get_discord_avatar_url(discord_id):
    """
    Get Discord avatar URL for a user
    """
    try:
        # Discord CDN URL format for avatars
        # We'll need to get the avatar hash from Discord API or use default
        
        # For now, we'll try to get user info from Discord API if we have a bot token
        bot_token = os.environ.get('DISCORD_BOT_TOKEN')
        if not bot_token:
            return None
            
        # Get user info from Discord API
        user_req = urllib.request.Request(
            f'https://discord.com/api/v10/users/{discord_id}',
            headers={
                'Authorization': f'Bot {bot_token}',
                'User-Agent': f'WordWebs-Bot/1.0',
                'Accept': 'application/json'
            }
        )
        
        with urllib.request.urlopen(user_req) as response:
            if response.status == 200:
                user_data = json.loads(response.read().decode('utf-8'))
                avatar_hash = user_data.get('avatar')
                
                if avatar_hash:
                    # Return CDN URL for avatar
                    return f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png?size=128"
                else:
                    # Return default avatar URL
                    discriminator = int(user_data.get('discriminator', '0'))
                    default_avatar_id = discriminator % 5
                    return f"https://cdn.discordapp.com/embed/avatars/{default_avatar_id}.png"
            else:
                print(f"Failed to get Discord user info: {response.status}")
                return None
                
    except Exception as e:
        print(f"Error getting Discord avatar for {discord_id}: {str(e)}")
        return None




def format_completion_time(seconds):
    """Format completion time in human-readable format"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        return f"{minutes}m {remaining_seconds}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"


# For local testing
if __name__ == "__main__":
    # Test the function locally
    test_event = {}
    result = lambda_handler(test_event, {})
    print("Test result:", result)