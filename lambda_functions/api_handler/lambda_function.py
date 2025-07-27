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
from shared.dynamodb_client import DynamoDBClient


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
            return get_daily_puzzle(query_params)
        elif http_method == 'POST' and raw_path == '/submit-guess':
            return submit_guess(body, event)
        elif http_method == 'GET' and raw_path == '/leaderboard':
            return get_leaderboard(query_params)
        elif http_method == 'GET' and raw_path == '/player-stats':
            return get_player_stats(query_params, event)
        elif http_method == 'POST' and raw_path == '/discord-oauth/token':
            return exchange_discord_token(body)
        elif http_method == 'POST' and raw_path == '/discord-oauth/refresh':
            return refresh_discord_token(body)
        elif http_method == 'GET' and raw_path == '/discord-oauth/verify':
            return verify_discord_token(query_params)
        elif http_method == 'GET' and raw_path == '/':
            return create_response(200, {'message': 'WordWebs API is running'})
        else:
            return create_response(404, {'error': 'Endpoint not found'})
            
    except Exception as e:
        return create_response(500, {'error': f'Internal server error: {str(e)}'})

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

def get_daily_puzzle(query_params):
    """Get today's puzzle"""
    try:
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
        return create_response(500, {'error': f'Failed to get daily puzzle: {str(e)}'})

def submit_guess(body, event):
    """Submit a player's guess and track their progress"""
    try:
        # Verify Discord authentication
        user = verify_discord_user(event)
        if not user:
            return create_response(401, {'error': 'Authentication required'})
        
        # Validate required fields
        required_fields = ['puzzle_id', 'guess', 'is_final']
        for field in required_fields:
            if field not in body:
                return create_response(400, {'error': f'Missing required field: {field}'})
        
        # Use authenticated user info instead of trusting client data
        discord_id = user['id']
        display_name = user['username']
        
        db = DynamoDBClient()
        
        # Get or create player
        player = db.get_or_create_player(discord_id, display_name)
        
        # For final submission, save complete game session
        if body['is_final']:
            completed = body.get('completed', False)
            completion_time = body.get('completion_time')
            all_guesses = body.get('all_guesses', [])
            
            # Get current date in EST for puzzle_date
            est = pytz.timezone('US/Eastern')
            current_date = datetime.now(est).strftime('%Y-%m-%d')
            
            session_id = db.save_game_session(
                discord_id,
                display_name,
                current_date,
                body['puzzle_id'], 
                all_guesses, 
                completed, 
                completion_time
            )
            
            response_data = {
                'session_id': session_id,
                'discord_id': player['discord_id'],
                'message': 'Game session saved successfully'
            }
            
            # If game completed, add leaderboard position
            if completed:
                leaderboard = db.get_daily_leaderboard(current_date)
                
                # Find player's position
                for idx, entry in enumerate(leaderboard):
                    if entry['display_name'] == display_name:
                        response_data['leaderboard_position'] = idx + 1
                        break
        else:
            # Just acknowledge the guess for real-time tracking
            response_data = {
                'message': 'Guess received',
                'discord_id': player['discord_id']
            }
        
        return create_response(200, response_data)
        
    except Exception as e:
        return create_response(500, {'error': f'Failed to submit guess: {str(e)}'})

def get_leaderboard(query_params):
    """Get daily leaderboard"""
    try:
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
        return create_response(500, {'error': f'Failed to get leaderboard: {str(e)}'})

def get_player_stats(query_params, event):
    """Get player statistics"""
    try:
        # Verify Discord authentication
        user = verify_discord_user(event)
        if not user:
            return create_response(401, {'error': 'Authentication required'})
        
        # Use authenticated user's ID or allow querying other users
        discord_id = query_params.get('discord_id', user['id'])
        
        db = DynamoDBClient()
        stats = db.get_player_stats(discord_id)
        
        if not stats:
            return create_response(404, {'error': 'Player not found'})
        
        # Stats are already formatted by DynamoDBClient
        formatted_stats = stats
        
        return create_response(200, formatted_stats)
        
    except Exception as e:
        return create_response(500, {'error': f'Failed to get player stats: {str(e)}'})

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
                'User-Agent': 'WordWebs-Discord-Activity/1.0 (https://wordwebs.onrender.com)',
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
                    return create_response(400, {'error': f'Discord API error {response.status}: {error_text}'})
                
                response_body = response.read()
                # Handle gzip encoding
                if response.headers.get('Content-Encoding') == 'gzip':
                    response_body = gzip.decompress(response_body)
                token_response = json.loads(response_body.decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if hasattr(e, 'read') else str(e)
            return create_response(500, {'error': f'Discord API HTTP Error {e.code}: {error_body}'})
        except Exception as e:
            return create_response(500, {'error': f'Request failed: {str(e)}'})
        
        # Get user info with the access token
        user_req = urllib.request.Request(
            'https://discord.com/api/users/@me',
            headers={
                'Authorization': f'Bearer {token_response["access_token"]}',
                'User-Agent': 'WordWebs-Discord-Activity/1.0 (https://wordwebs.onrender.com)',
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
                    return create_response(400, {'error': f'Failed to get user info: {error_text}'})
                
                user_body = user_response.read()
                # Handle gzip encoding
                if user_response.headers.get('Content-Encoding') == 'gzip':
                    user_body = gzip.decompress(user_body)
                user_data = json.loads(user_body.decode('utf-8'))
        except Exception as e:
            return create_response(500, {'error': f'Failed to get user info: {str(e)}'})
        
        # Return token and user info
        return create_response(200, {
            'access_token': token_response['access_token'],
            'refresh_token': token_response.get('refresh_token'),
            'expires_in': token_response.get('expires_in', 3600),
            'user': {
                'id': user_data['id'],
                'username': user_data['username'],
                'avatar': user_data.get('avatar')
            }
        })
        
    except Exception as e:
        return create_response(500, {'error': f'Failed to exchange token: {str(e)}'})

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
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
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
        return create_response(500, {'error': f'Failed to refresh token: {str(e)}'})

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
            headers={'Authorization': f'Bearer {token}'}
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
            headers={'Authorization': f'Bearer {token}'}
        )
        
        with urllib.request.urlopen(user_req) as response:
            if response.status != 200:
                return None
            
            user_data = json.loads(response.read().decode('utf-8'))
            return {
                'id': user_data['id'],
                'username': user_data['username'],
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