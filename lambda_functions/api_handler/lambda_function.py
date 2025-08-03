import sys
import os
sys.path.append('/opt')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import json
from datetime import datetime
import pytz
import urllib.request
import urllib.parse
import gzip
import base64
from shared.dynamodb_client import DynamoDBClient
from shared.discord_utils import send_discord_message_with_image, edit_discord_message_with_image, generate_game_state_message


def lambda_handler(event, context):
    """
    Lambda Function URL handler for all API requests
    """
    
    try:
        # Parse the request (Function URL format)
        http_method = event.get('requestContext', {}).get('http', {}).get('method', '')
        raw_path = event.get('rawPath', '')
        query_params = event.get('queryStringParameters') or {}
        
        # Parse body if present
        body = {}
        if event.get('body'):
            try:
                body = json.loads(event['body'])
            except json.JSONDecodeError:
                return create_response(400, {'error': 'Invalid JSON in request body'})
        
        # Route requests
        if http_method == 'GET' and raw_path == '/daily-puzzle':
            return get_daily_puzzle(query_params, event)
        elif http_method == 'GET' and raw_path == '/leaderboard':
            return get_leaderboard(query_params, event)
        elif http_method == 'POST' and raw_path == '/discord-oauth/token':
            return exchange_discord_token(body)
        elif http_method == 'POST' and raw_path == '/discord-oauth/refresh':
            return refresh_discord_token(body)
        elif http_method == 'GET' and raw_path == '/discord-oauth/verify':
            return verify_discord_token(query_params)
        elif http_method == 'GET' and raw_path == '/game-state':
            return get_game_state(query_params, event)
        elif http_method == 'POST' and raw_path == '/save-progress':
            return save_game_progress(body, event)
        elif http_method == 'POST' and raw_path == '/send-bot-message':
            return send_bot_message(body, event)
        elif http_method == 'GET' and raw_path == '/':
            return create_response(200, {'message': 'Word Webs API is running'})
        else:
            return create_response(404, {'error': 'Endpoint not found'})
            
    except Exception as e:
        return create_response(500, {'error': 'Internal server error'})

def create_response(status_code, body, headers=None):
    """Create standardized API response"""
    default_headers = {
        'Content-Type': 'application/json'
    }
    
    if headers:
        default_headers.update(headers)
    
    return {
        'statusCode': status_code,
        'headers': default_headers,
        'body': json.dumps(body)
    }

def get_daily_puzzle(query_params, event):
    """Get today's puzzle"""
    try:
        # Verify Discord authentication
        user = verify_discord_user(event)
        if not user:
            return create_response(401, {'error': 'Authentication required'})
        
        # Get current date in EST
        est = pytz.timezone('US/Eastern')
        current_date = datetime.now(est).strftime('%Y-%m-%d')
        
        # Allow override for testing
        date = query_params.get('date', current_date)
        
        db = DynamoDBClient()
        puzzle = db.get_daily_puzzle(date)
        
        if not puzzle:
            return create_response(404, {'error': f'No puzzle found for {date}'})
        
        # Include groups for frontend validation
        response_data = {
            'id': puzzle['puzzle_id'],
            'words': puzzle['words'],
            'groups': puzzle['groups'],
            'date': date
        }
        
        return create_response(200, response_data)
        
    except Exception as e:
        return create_response(500, {'error': 'Failed to retrieve daily puzzle'})


def get_leaderboard(query_params, event):
    """Get daily leaderboard"""
    try:
        # Verify Discord authentication
        user = verify_discord_user(event)
        if not user:
            return create_response(401, {'error': 'Authentication required'})
        
        # Get date (default to today)
        est = pytz.timezone('US/Eastern')
        current_date = datetime.now(est).strftime('%Y-%m-%d')
        date = query_params.get('date', current_date)
        
        db = DynamoDBClient()
        leaderboard = db.get_daily_leaderboard(date)
        
        # Leaderboard is already formatted by DynamoDBClient
        formatted_leaderboard = leaderboard
        
        return create_response(200, {
            'date': date,
            'leaderboard': formatted_leaderboard,
            'total_players': len(formatted_leaderboard)
        })
        
    except Exception as e:
        return create_response(500, {'error': 'Failed to retrieve leaderboard'})


def exchange_discord_token(body):
    """Exchange Discord authorization code for access token"""
    try:
        # Validate required fields
        if 'code' not in body:
            return create_response(400, {'error': 'Missing required field: code'})
        
        # Get Discord client credentials from environment
        client_id = os.environ.get('DISCORD_CLIENT_ID')
        client_secret = os.environ.get('DISCORD_CLIENT_SECRET')
        redirect_uri = os.environ.get('DISCORD_REDIRECT_URI')
        
        if not client_id or not client_secret or not redirect_uri:
            return create_response(500, {'error': 'Discord credentials not configured'})
        
        # Exchange code for token with Discord
        token_data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'authorization_code',
            'code': body['code'],
            'redirect_uri': redirect_uri
        }
        
        # Make request to Discord token endpoint
        req_data = urllib.parse.urlencode(token_data).encode('utf-8')
        req = urllib.request.Request(
            'https://discord.com/api/oauth2/token',
            data=req_data,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': f'WordWebs-Discord-Activity/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})',
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate'
            }
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                if response.status != 200:
                    error_body = response.read()
                    # Handle gzip encoding
                    if response.headers.get('Content-Encoding') == 'gzip':
                        error_body = gzip.decompress(error_body)
                    error_text = error_body.decode('utf-8')
                    return create_response(400, {'error': 'Discord authentication failed'})
                
                response_body = response.read()
                # Handle gzip encoding
                if response.headers.get('Content-Encoding') == 'gzip':
                    response_body = gzip.decompress(response_body)
                token_response = json.loads(response_body.decode('utf-8'))
        except urllib.error.HTTPError as e:
            return create_response(500, {'error': 'Discord authentication service unavailable'})
        except Exception as e:
            return create_response(500, {'error': 'Authentication request failed'})
        
        # Get user info with the access token
        user_req = urllib.request.Request(
            'https://discord.com/api/users/@me',
            headers={
                'Authorization': f'Bearer {token_response["access_token"]}',
                'User-Agent': f'WordWebs-Discord-Activity/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})',
                'Accept': 'application/json'
            }
        )
        
        try:
            with urllib.request.urlopen(user_req) as user_response:
                if user_response.status != 200:
                    error_body = user_response.read()
                    # Handle gzip encoding
                    if user_response.headers.get('Content-Encoding') == 'gzip':
                        error_body = gzip.decompress(error_body)
                    error_text = error_body.decode('utf-8')
                    return create_response(400, {'error': 'Failed to retrieve user information'})
                
                user_body = user_response.read()
                # Handle gzip encoding
                if user_response.headers.get('Content-Encoding') == 'gzip':
                    user_body = gzip.decompress(user_body)
                user_data = json.loads(user_body.decode('utf-8'))
        except Exception as e:
            return create_response(500, {'error': 'Failed to retrieve user information'})
        
        # Return token and user info
        return create_response(200, {
            'access_token': token_response['access_token'],
            'refresh_token': token_response.get('refresh_token'),
            'expires_in': token_response.get('expires_in', 3600),
            'user': {
                'id': user_data['id'],
                'username': user_data['username'],
                'display_name': user_data.get('global_name') or user_data.get('display_name') or user_data['username'],
                'avatar': user_data.get('avatar')
            }
        })
        
    except Exception as e:
        return create_response(500, {'error': 'Token exchange failed'})

def refresh_discord_token(body):
    """Refresh Discord access token"""
    try:
        # Validate required fields
        if 'refresh_token' not in body:
            return create_response(400, {'error': 'Missing required field: refresh_token'})
        
        # Get Discord client credentials from environment
        client_id = os.environ.get('DISCORD_CLIENT_ID')
        client_secret = os.environ.get('DISCORD_CLIENT_SECRET')
        
        if not client_id or not client_secret:
            return create_response(500, {'error': 'Discord credentials not configured'})
        
        # Refresh token with Discord
        token_data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': body['refresh_token']
        }
        
        req_data = urllib.parse.urlencode(token_data).encode('utf-8')
        req = urllib.request.Request(
            'https://discord.com/api/oauth2/token',
            data=req_data,
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': f'WordWebs-Discord-Activity/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})',
                'Accept': 'application/json'
            }
        )
        
        with urllib.request.urlopen(req) as response:
            if response.status != 200:
                return create_response(400, {'error': 'Failed to refresh token'})
            
            token_response = json.loads(response.read().decode('utf-8'))
        
        return create_response(200, {
            'access_token': token_response['access_token'],
            'refresh_token': token_response.get('refresh_token'),
            'expires_in': token_response.get('expires_in', 3600)
        })
        
    except Exception as e:
        print(f"Error refreshing Discord token: {str(e)}")
        return create_response(500, {'error': 'Token refresh failed'})

def verify_discord_token(query_params):
    """Verify Discord access token and return user info"""
    try:
        # Get token from Authorization header or query param
        auth_header = query_params.get('authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        else:
            token = query_params.get('token', '')
        
        if not token:
            return create_response(400, {'error': 'Missing access token'})
        
        # Verify token with Discord
        user_req = urllib.request.Request(
            'https://discord.com/api/users/@me',
            headers={
                'Authorization': f'Bearer {token}',
                'User-Agent': f'WordWebs-Discord-Activity/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})',
                'Accept': 'application/json'
            }
        )
        
        with urllib.request.urlopen(user_req) as user_response:
            if user_response.status != 200:
                return create_response(401, {'error': 'Invalid or expired token'})
            
            user_data = json.loads(user_response.read().decode('utf-8'))
        
        return create_response(200, {
            'valid': True,
            'user': {
                'id': user_data['id'],
                'username': user_data['username'],
                'avatar': user_data.get('avatar')
            }
        })
        
    except Exception as e:
        print(f"Error verifying Discord token: {str(e)}")
        return create_response(401, {'error': 'Token verification failed'})

def get_game_state(query_params, event):
    """Get current game state for authenticated user"""
    try:
        # Verify Discord authentication
        user = verify_discord_user(event)
        if not user:
            return create_response(401, {'error': 'Authentication required'})
        
        # Get date (default to today)
        est = pytz.timezone('US/Eastern')
        current_date = datetime.now(est).strftime('%Y-%m-%d')
        date = query_params.get('date', current_date)
        
        discord_id = user['id']
        
        db = DynamoDBClient()
        
        # Get existing game session
        session = db.get_user_game_session(discord_id, date)
        
        # Check if user has already completed today's puzzle
        if session and session.get('completed', False):
            return create_response(200, {
                'game_status': 'completed',
                'message': 'You have already completed today\'s puzzle!',
                'solved_groups': session.get('solved_groups', []),
                'attempts_remaining': session.get('attempts_remaining', 0),
                'selected_words': [],
                'guesses': session.get('guesses', []),
                'session_id': session['session_id']
            })
        
        # Check if user failed the puzzle (attempts exhausted but not completed)
        if session and session.get('attempts_remaining', 4) == 0 and not session.get('completed', False):
            return create_response(200, {
                'game_status': 'failed',
                'message': 'You already used all attempts for today\'s puzzle.',
                'solved_groups': session.get('solved_groups', []),
                'attempts_remaining': 0,
                'selected_words': [],
                'guesses': session.get('guesses', []),
                'session_id': session['session_id']
            })
        
        if session:
            # Return existing progress
            return create_response(200, {
                'game_status': session.get('game_status', 'in_progress'),
                'attempts_remaining': session.get('attempts_remaining', 4),
                'solved_groups': session.get('solved_groups', []),
                'selected_words': session.get('selected_words', []),
                'guesses': session.get('guesses', []),
                'session_id': session['session_id']
            })
        else:
            # No existing session - fresh start
            return create_response(200, {
                'game_status': 'new',
                'attempts_remaining': 4,
                'solved_groups': [],
                'selected_words': [],
                'guesses': []
            })
            
    except Exception as e:
        return create_response(500, {'error': 'Failed to retrieve game state'})

def save_game_progress(body, event):
    """Save game progress after each guess"""
    try:
        print(f"=== save_game_progress called ===")
        print(f"Request body keys: {list(body.keys()) if body else 'None'}")
        print(f"Request body: {json.dumps(body, default=str) if body else 'None'}")
        
        # Verify Discord authentication
        user = verify_discord_user(event)
        if not user:
            print("Authentication failed - no user")
            return create_response(401, {'error': 'Authentication required'})
        
        print(f"User authenticated: {user}")
        
        # Validate required fields
        required_fields = ['puzzle_id', 'guess', 'attempts_remaining', 'solved_groups']
        for field in required_fields:
            if field not in body:
                print(f"Missing required field: {field}")
                return create_response(400, {'error': f'Missing required field: {field}'})
        
        print("All required fields present")
        
        discord_id = user['id']
        display_name = user['display_name']
        
        print(f"Discord ID: {discord_id}, Display name: {display_name}")
        
        # Get current date in EST
        est = pytz.timezone('US/Eastern')
        current_date = datetime.now(est).strftime('%Y-%m-%d')
        print(f"Current date (EST): {current_date}")
        
        db = DynamoDBClient()
        print("DynamoDB client initialized")
        
        # Get or create player (this ensures player exists in database)
        try:
            player = db.get_or_create_player(discord_id, display_name)
            print(f"Player retrieved/created: {player['discord_id']}")
        except Exception as e:
            print(f"Error creating/getting player: {str(e)}")
            return create_response(500, {'error': 'Failed to create player profile'})
        
        # Check if user has already completed today's puzzle
        try:
            completed_check = db.has_user_completed_daily_puzzle(discord_id, current_date)
            print(f"User completed puzzle check: {completed_check}")
            if completed_check:
                print("User already completed today's puzzle")
                return create_response(400, {'error': 'You have already completed today\'s puzzle!'})
        except Exception as e:
            print(f"Error checking if user completed puzzle: {str(e)}")
            # Continue anyway, don't block on this check
        
        # Get current guesses and add the new one
        try:
            existing_session = db.get_user_game_session(discord_id, current_date)
            print(f"Existing session: {existing_session}")
            current_guesses = existing_session.get('guesses', []) if existing_session else []
            current_guesses.append(body['guess'])
            print(f"Current guesses after adding new: {len(current_guesses)} guesses")
        except Exception as e:
            print(f"Error getting existing session: {str(e)}")
            current_guesses = [body['guess']]
            existing_session = None
        
        # Save progress
        print("About to save game progress to database...")
        try:
            session_id = db.save_game_progress(
                discord_id=discord_id,
                display_name=display_name,
                puzzle_date=current_date,
                puzzle_id=body['puzzle_id'],
                guesses=current_guesses,
                attempts_remaining=body['attempts_remaining'],
                solved_groups=body['solved_groups'],
                selected_words=body.get('selected_words', [])
            )
            print(f"Game progress saved successfully, session_id: {session_id}")
        except Exception as e:
            print(f"Error saving game progress: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            raise e
        
        # Handle Discord messaging for significant game events
        existing_solved_count = len(existing_session.get('solved_groups', [])) if existing_session else 0
        new_solved_count = len(body['solved_groups'])
        existing_attempts = existing_session.get('attempts_remaining', 4) if existing_session else 4
        new_attempts = body['attempts_remaining']
        
        should_send_discord_message = (
            new_solved_count == 4 or  # Game completed
            body['attempts_remaining'] == 0 or  # Game failed (no attempts left)
            new_solved_count > existing_solved_count or  # New group found
            (new_solved_count == existing_solved_count and new_attempts < existing_attempts)  # Failed attempt (wrong guess)
        )
        
        print(f"Discord messaging check:")
        print(f"  - Existing solved groups: {existing_solved_count}")
        print(f"  - New solved groups: {new_solved_count}")
        print(f"  - Existing attempts: {existing_attempts}")
        print(f"  - New attempts: {new_attempts}")
        print(f"  - Should send Discord message: {should_send_discord_message}")
        print(f"  - Has channel_id: {bool(body.get('channel_id'))}")
        print(f"  - Has image_data: {bool(body.get('image_data'))}")
        print(f"  - Channel ID: {body.get('channel_id', 'None')}")
        print(f"  - Image data length: {len(body.get('image_data', '')) if body.get('image_data') else 0}")
        
        discord_message_sent = False
        if should_send_discord_message and body.get('channel_id') and body.get('image_data'):
            print("Attempting to send Discord message...")
            try:
                discord_message_sent = handle_discord_messaging(
                    session_id=session_id,
                    game_state={
                        'solved_groups': body['solved_groups'],
                        'guesses': current_guesses,
                        'attempts_remaining': body['attempts_remaining']
                    },
                    player_info={'username': display_name, 'id': discord_id},
                    puzzle_number=body.get('puzzle_number', 1),
                    channel_id=body['channel_id'],
                    image_data=body['image_data'],
                    db=db
                )
                print(f"Discord messaging result: {discord_message_sent}")
            except Exception as e:
                print(f"Error in Discord messaging: {str(e)}")
                import traceback
                print(f"Discord messaging traceback: {traceback.format_exc()}")
                # Don't fail the entire request if Discord messaging fails
                discord_message_sent = False
        else:
            print("Skipping Discord message (conditions not met)")
        
        # Register Discord channel if provided (for daily summaries)
        if body.get('channel_id'):
            try:
                # Get guild info from request body (provided by Discord SDK)
                channel_id = body['channel_id']
                guild_id = body.get('guild_id')  # Should be provided by frontend
                guild_name = body.get('guild_name', 'Discord Server')
                channel_name = body.get('channel_name', 'wordwebs')
                
                # Skip registration if we don't have a guild_id
                if not guild_id:
                    print(f"No guild_id provided for channel {channel_id}, skipping registration")
                    # Still continue with game progress saving
                else:
                    print(f"Registering channel {channel_id} for guild {guild_id}")
                    
                    channel_registered = db.register_discord_channel(
                        channel_id=channel_id,
                        guild_id=guild_id,
                        guild_name=guild_name,
                        channel_name=channel_name
                    )
                    print(f"Discord channel registration result: {channel_registered}")
                    
                    # Update channel activity timestamp
                    if channel_registered:
                        db.update_channel_activity(channel_id)
                        print(f"Updated activity for channel {channel_id}")
                    
            except Exception as e:
                print(f"Error registering Discord channel: {str(e)}")
                # Don't fail the entire request if channel registration fails
        else:
            print("No channel_id provided, skipping channel registration")
        
        # Check if game is completed or failed
        print("Checking game completion status...")
        if len(body['solved_groups']) == 4:
            print("Game completed! Updating completion status...")
            completion_time = body.get('completion_time')
            print(f"Completion time: {completion_time}")
            if completion_time:
                try:
                    db.complete_game_session(session_id, True, completion_time)
                    print("Game session marked as completed")
                    
                    # Update player stats
                    db._update_player_stats(discord_id, completion_time)
                    print("Player stats updated")
                except Exception as e:
                    print(f"Error updating completion status: {str(e)}")
        elif body['attempts_remaining'] == 0:
            print("Game failed! Updating failure status...")
            try:
                db.complete_game_session(session_id, False)
                print("Game session marked as failed")
                
                # Just increment total games
                db.tables['players'].update_item(
                    Key={'discord_id': discord_id},
                    UpdateExpression='ADD total_games :one SET last_played = :last',
                    ExpressionAttributeValues={
                        ':one': 1,
                        ':last': datetime.utcnow().isoformat()
                    }
                )
                print("Player total games incremented")
            except Exception as e:
                print(f"Error updating failure status: {str(e)}")
        else:
            print("Game still in progress")
        
        response_data = {
            'session_id': session_id,
            'message': 'Progress saved successfully'
        }
        
        if discord_message_sent:
            response_data['discord_message_sent'] = True
        
        print(f"Returning success response: {response_data}")
        return create_response(200, response_data)
        
    except Exception as e:
        print(f"CRITICAL ERROR in save_game_progress: {str(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        return create_response(500, {'error': 'Failed to save game progress'})

def send_bot_message(body, event):
    """Send Discord bot message with game state image"""
    try:
        print(f"send_bot_message called with body keys: {list(body.keys()) if body else 'None'}")
        
        # Verify Discord authentication
        user = verify_discord_user(event)
        if not user:
            print("Authentication failed - no user")
            return create_response(401, {'error': 'Authentication required'})
        
        print(f"User authenticated: {user.get('username', 'unknown')}")
        
        # Validate required fields
        required_fields = ['channel_id', 'content', 'image_data']
        for field in required_fields:
            if field not in body:
                print(f"Missing required field: {field}")
                return create_response(400, {'error': f'Missing required field: {field}'})
        
        print("All required fields present")
        
        # Get Discord bot token
        bot_token = os.environ.get('DISCORD_BOT_TOKEN')
        if not bot_token:
            print("Discord bot token not configured")
            return create_response(500, {'error': 'Discord bot token not configured'})
        
        print("Bot token found")
        
        channel_id = body['channel_id']
        content = body['content']
        image_data = body['image_data']
        
        print(f"Channel ID: {channel_id}")
        print(f"Content length: {len(content)}")
        print(f"Image data length: {len(image_data)}")
        
        # Convert base64 image data to bytes
        try:
            # Remove data URL prefix if present (data:image/png;base64,)
            if image_data.startswith('data:'):
                image_data = image_data.split(',', 1)[1]
            
            image_bytes = base64.b64decode(image_data)
            print(f"Image decoded, size: {len(image_bytes)} bytes")
        except Exception as e:
            print(f"Image decoding error: {str(e)}")
            return create_response(400, {'error': 'Invalid image data format'})
        
        # Send Discord message with image
        print("Attempting to send Discord message...")
        message_id = send_discord_message_with_image(
            channel_id=channel_id,
            content=content,
            image_bytes=image_bytes,
            bot_token=bot_token
        )
        
        print(f"Discord message result: {message_id}")
        
        if message_id:
            return create_response(200, {'success': True, 'message': 'Bot message sent successfully', 'message_id': message_id})
        else:
            return create_response(500, {'error': 'Failed to send Discord message'})
            
    except Exception as e:
        print(f"Exception in send_bot_message: {str(e)}")
        print(f"Exception type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return create_response(500, {'error': 'Failed to send message'})



def handle_discord_messaging(session_id: str, game_state: dict, player_info: dict, 
                            puzzle_number: int, channel_id: str, image_data: str, db) -> bool:
    """
    Handle Discord messaging for game state updates - either create new message or edit existing one
    """
    try:
        # Get Discord bot token
        bot_token = os.environ.get('DISCORD_BOT_TOKEN')
        if not bot_token:
            print("Discord bot token not configured")
            return False
        
        # Generate message content
        message_content = generate_game_state_message(game_state, player_info, puzzle_number)
        
        # Convert base64 image data to bytes
        try:
            if image_data.startswith('data:'):
                image_data = image_data.split(',', 1)[1]
            image_bytes = base64.b64decode(image_data)
        except Exception as e:
            print(f"Image decoding error: {str(e)}")
            return False
        
        # Check if we already have a Discord message for this session
        existing_message = db.get_session_discord_message(session_id)
        
        if existing_message and existing_message.get('message_id'):
            # Edit existing message (which deletes old and creates new)
            print(f"Editing existing Discord message {existing_message['message_id']}")
            new_message_id = edit_discord_message_with_image(
                channel_id=channel_id,
                message_id=existing_message['message_id'],
                content=message_content,
                image_bytes=image_bytes,
                bot_token=bot_token
            )
            
            if new_message_id:
                # Update with the new message ID
                print(f"Updating database with new message ID: {new_message_id}")
                db.update_discord_message_info(session_id, new_message_id, channel_id)
                success = True
            else:
                success = False
        else:
            # Create new message
            print(f"Creating new Discord message in channel {channel_id}")
            discord_message_id = send_discord_message_with_image(
                channel_id=channel_id,
                content=message_content,
                image_bytes=image_bytes,
                bot_token=bot_token
            )
            
            print(f"Discord message ID returned: {discord_message_id} (type: {type(discord_message_id)})")
            if discord_message_id:
                # Save Discord message info to session
                print(f"Saving Discord message info: session_id={session_id}, message_id={discord_message_id}, channel_id={channel_id}")
                db.update_discord_message_info(session_id, discord_message_id, channel_id)
                success = True
            else:
                success = False
        
        print(f"Discord messaging result: {success}")
        return success
        
    except Exception as e:
        print(f"Error in handle_discord_messaging: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return False


def verify_discord_user(event):
    """Helper function to verify Discord token from request headers"""
    try:
        # Get authorization header
        headers = event.get('headers', {})
        auth_header = headers.get('authorization', '') or headers.get('Authorization', '')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return None
        
        token = auth_header[7:]
        
        # Verify with Discord API
        user_req = urllib.request.Request(
            'https://discord.com/api/users/@me',
            headers={
                'Authorization': f'Bearer {token}',
                'User-Agent': f'WordWebs-Discord-Activity/1.0 ({os.environ.get("DISCORD_REDIRECT_URI")})',
                'Accept': 'application/json'
            }
        )
        
        with urllib.request.urlopen(user_req) as response:
            if response.status != 200:
                return None
            
            user_data = json.loads(response.read().decode('utf-8'))
            return {
                'id': user_data['id'],
                'username': user_data['username'],
                'display_name': user_data.get('global_name') or user_data.get('display_name') or user_data['username'],
                'avatar': user_data.get('avatar')
            }
    except:
        return None

# For local testing
if __name__ == "__main__":
    # Test daily puzzle endpoint
    test_event = {
        'httpMethod': 'GET',
        'path': '/api/daily-puzzle',
        'queryStringParameters': {}
    }
    
    result = lambda_handler(test_event, {})
    print("Daily puzzle test:", result)