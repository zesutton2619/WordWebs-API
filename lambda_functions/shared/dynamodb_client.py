import boto3
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional
from decimal import Decimal
import uuid

class DynamoDBClient:
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb')
        self.tables = {
            'daily_puzzles': self.dynamodb.Table('wordwebs-daily-puzzles'),
            'players': self.dynamodb.Table('wordwebs-players'),
            'game_sessions': self.dynamodb.Table('wordwebs-game-sessions'),
            'historical_puzzles': self.dynamodb.Table('wordwebs-historical-puzzles'),
            'theme_suggestions': self.dynamodb.Table('wordwebs-theme-suggestions'),
            'discord_channels': self.dynamodb.Table('wordwebs-discord-channels')
        }
    
    def get_daily_puzzle(self, date: str) -> Optional[Dict[str, Any]]:
        """Get puzzle for specific date"""
        try:
            response = self.tables['daily_puzzles'].get_item(
                Key={'puzzle_date': date}
            )
            item = response.get('Item')
            if item:
                # Convert DynamoDB Decimals to regular numbers for JSON serialization
                return self._convert_decimals(item)
            return None
        except Exception as e:
            print(f"Error getting daily puzzle: {e}")
            return None
    
    def save_daily_puzzle(self, date: str, words: List[str], groups: List[Dict]) -> str:
        """Save daily puzzle"""
        puzzle_id = str(uuid.uuid4())
        
        item = {
            'puzzle_date': date,
            'puzzle_id': puzzle_id,
            'words': words,
            'groups': groups,
            'created_at': datetime.utcnow().isoformat()
        }
        
        self.tables['daily_puzzles'].put_item(Item=item)
        return puzzle_id
    
    def check_duplicate_groups(self, groups: List[Dict]) -> bool:
        """Check if any group already exists in historical puzzles"""
        for group in groups:
            group_hash = self._hash_group(group['words'])
            
            try:
                response = self.tables['historical_puzzles'].get_item(
                    Key={'group_hash': group_hash}
                )
                if response.get('Item'):
                    return True
            except Exception as e:
                print(f"Error checking duplicates: {e}")
                continue
        
        return False
    
    def save_historical_puzzle(self, groups: List[Dict]):
        """Save groups to historical puzzles for duplicate checking"""
        for group in groups:
            group_hash = self._hash_group(group['words'])
            
            item = {
                'group_hash': group_hash,
                'words': group['words'],
                'category': group['category'],
                'difficulty': group['difficulty'],
                'created_at': datetime.utcnow().isoformat()
            }
            
            self.tables['historical_puzzles'].put_item(Item=item)
    
    def get_or_create_player(self, discord_id: str, display_name: str) -> Dict[str, Any]:
        """Get existing player or create new one"""
        try:
            response = self.tables['players'].get_item(
                Key={'discord_id': discord_id}
            )
            
            if response.get('Item'):
                # Update display name if changed
                player = response['Item']
                if player['display_name'] != display_name:
                    self.tables['players'].update_item(
                        Key={'discord_id': discord_id},
                        UpdateExpression='SET display_name = :name, last_played = :last',
                        ExpressionAttributeValues={
                            ':name': display_name,
                            ':last': datetime.utcnow().isoformat()
                        }
                    )
                    player['display_name'] = display_name
                return player
            else:
                # Create new player
                player = {
                    'discord_id': discord_id,
                    'display_name': display_name,
                    'total_games': 0,
                    'games_won': 0,
                    'best_time': None,
                    'created_at': datetime.utcnow().isoformat(),
                    'last_played': datetime.utcnow().isoformat()
                }
                
                self.tables['players'].put_item(Item=player)
                return player
                
        except Exception as e:
            print(f"Error with player: {e}")
            raise e
    
    
    def get_daily_leaderboard(self, date: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get daily leaderboard sorted by completion time (completed games only)"""
        try:
            response = self.tables['game_sessions'].query(
                IndexName='puzzle-date-time-index',
                KeyConditionExpression='puzzle_date = :date',
                FilterExpression='completed = :completed',
                ExpressionAttributeValues={
                    ':date': date,
                    ':completed': True
                },
                ScanIndexForward=True,  # Sort by completion_time ascending
                Limit=limit
            )
            
            leaderboard = []
            for idx, item in enumerate(response['Items']):
                leaderboard.append({
                    'rank': idx + 1,
                    'display_name': item['display_name'],
                    'completion_time': int(item['completion_time']),
                    'completed': item['completed']
                })
            
            return leaderboard
            
        except Exception as e:
            print(f"Error getting leaderboard: {e}")
            return []

    def get_all_daily_games(self, date: str, channel_id: str = None) -> List[Dict[str, Any]]:
        """Get all games (completed and incomplete) for a specific date, optionally filtered by channel"""
        try:
            if channel_id:
                # Filter by both date and channel
                response = self.tables['game_sessions'].scan(
                    FilterExpression='puzzle_date = :date AND discord_channel_id = :channel_id',
                    ExpressionAttributeValues={
                        ':date': date,
                        ':channel_id': channel_id
                    }
                )
            else:
                # Get all games for the date (original behavior)
                response = self.tables['game_sessions'].scan(
                    FilterExpression='puzzle_date = :date',
                    ExpressionAttributeValues={
                        ':date': date
                    }
                )
            
            games = []
            completed_games = []
            incomplete_games = []
            
            for item in response['Items']:
                game_data = {
                    'display_name': item['display_name'],
                    'discord_id': item['discord_id'],
                    'completed': item['completed'],
                    'solved_groups_count': len(item.get('solved_groups', [])),
                    'attempts_used': 4 - item.get('attempts_remaining', 0),
                    'game_status': item.get('game_status', 'unknown')
                }
                
                if item.get('completion_time'):
                    game_data['completion_time'] = int(item['completion_time'])
                
                if item['completed']:
                    completed_games.append(game_data)
                else:
                    incomplete_games.append(game_data)
            
            # Sort completed games by completion time, incomplete by solved groups then attempts
            completed_games.sort(key=lambda x: x.get('completion_time', 0))
            incomplete_games.sort(key=lambda x: (-x['solved_groups_count'], x['attempts_used']))
            
            # Add ranks - completed games first, then incomplete
            rank = 1
            for game in completed_games:
                game['rank'] = rank
                games.append(game)
                rank += 1
            
            for game in incomplete_games:
                game['rank'] = rank
                games.append(game)
                rank += 1
            
            return games
            
        except Exception as e:
            print(f"Error getting all daily games: {e}")
            return []
    
    def get_player_stats(self, discord_id: str) -> Optional[Dict[str, Any]]:
        """Get player statistics"""
        try:
            response = self.tables['players'].get_item(
                Key={'discord_id': discord_id}
            )
            
            player = response.get('Item')
            if not player:
                return None
            
            # Calculate win rate
            total_games = player.get('total_games', 0)
            games_won = player.get('games_won', 0)
            win_rate = round((games_won / max(total_games, 1)) * 100, 1) if total_games > 0 else 0
            
            return {
                'total_games': total_games,
                'games_won': games_won,
                'win_rate': win_rate,
                'best_time': player.get('best_time'),
                'last_played': player.get('last_played')
            }
            
        except Exception as e:
            print(f"Error getting player stats: {e}")
            return None

    def get_user_game_session(self, discord_id: str, puzzle_date: str) -> Optional[Dict[str, Any]]:
        """Get user's existing game session for a specific date"""
        try:
            response = self.tables['game_sessions'].query(
                IndexName='discord-puzzle-index',
                KeyConditionExpression='discord_id = :discord_id AND puzzle_date = :date',
                ExpressionAttributeValues={
                    ':discord_id': discord_id,
                    ':date': puzzle_date
                },
                Limit=1
            )
            
            items = response.get('Items', [])
            if items:
                return self._convert_decimals(items[0])
            return None
            
        except Exception as e:
            print(f"Error getting user game session: {e}")
            return None

    def save_game_progress(self, discord_id: str, display_name: str, puzzle_date: str, 
                          puzzle_id: str, guesses: List[List[str]], attempts_remaining: int,
                          solved_groups: List[Dict], selected_words: List[str] = None) -> str:
        """Save or update game progress"""
        try:
            # Check if session already exists
            existing_session = self.get_user_game_session(discord_id, puzzle_date)
            
            if existing_session:
                session_id = existing_session['session_id']
                
                # Update existing session
                self.tables['game_sessions'].update_item(
                    Key={'session_id': session_id},
                    UpdateExpression='''SET guesses = :guesses, 
                                          attempts_remaining = :attempts, 
                                          solved_groups = :solved,
                                          selected_words = :selected,
                                          updated_at = :updated,
                                          game_status = :status''',
                    ExpressionAttributeValues={
                        ':guesses': guesses,
                        ':attempts': attempts_remaining,
                        ':solved': solved_groups,
                        ':selected': selected_words or [],
                        ':updated': datetime.utcnow().isoformat(),
                        ':status': 'in_progress' if attempts_remaining > 0 and len(solved_groups) < 4 else 
                                  ('completed' if len(solved_groups) == 4 else 'failed')
                    }
                )
            else:
                # Create new session
                session_id = str(uuid.uuid4())
                session_item = {
                    'session_id': session_id,
                    'discord_id': discord_id,
                    'display_name': display_name,
                    'puzzle_date': puzzle_date,
                    'puzzle_id': puzzle_id,
                    'guesses': guesses,
                    'attempts_remaining': attempts_remaining,
                    'solved_groups': solved_groups,
                    'selected_words': selected_words or [],
                    'game_status': 'in_progress',
                    'completed': False,
                    'created_at': datetime.utcnow().isoformat(),
                    'updated_at': datetime.utcnow().isoformat()
                }
                
                self.tables['game_sessions'].put_item(Item=session_item)
            
            return session_id
            
        except Exception as e:
            print(f"Error saving game progress: {e}")
            raise e
    
    def update_discord_message_info(self, session_id: str, discord_message_id: str, discord_channel_id: str):
        """Update Discord message information for a game session"""
        try:
            self.tables['game_sessions'].update_item(
                Key={'session_id': session_id},
                UpdateExpression='SET discord_message_id = :msg_id, discord_channel_id = :ch_id, message_sent = :sent, updated_at = :updated',
                ExpressionAttributeValues={
                    ':msg_id': discord_message_id,
                    ':ch_id': discord_channel_id,
                    ':sent': True,
                    ':updated': datetime.utcnow().isoformat()
                }
            )
        except Exception as e:
            print(f"Error updating Discord message info: {e}")
            raise e
    
    def get_session_discord_message(self, session_id: str) -> Optional[Dict[str, str]]:
        """Get Discord message information for a session"""
        try:
            response = self.tables['game_sessions'].get_item(
                Key={'session_id': session_id}
            )
            item = response.get('Item')
            if item and item.get('discord_message_id'):
                return {
                    'message_id': item['discord_message_id'],
                    'channel_id': item['discord_channel_id'],
                    'message_sent': item.get('message_sent', False)
                }
            return None
        except Exception as e:
            print(f"Error getting Discord message info: {e}")
            return None

    def complete_game_session(self, session_id: str, completed: bool, completion_time: Optional[int] = None):
        """Mark a game session as completed or failed"""
        try:
            update_expr = 'SET game_status = :status, completed = :completed, updated_at = :updated'
            expr_values = {
                ':status': 'completed' if completed else 'failed',
                ':completed': completed,
                ':updated': datetime.utcnow().isoformat()
            }
            
            if completion_time is not None:
                update_expr += ', completion_time = :time'
                expr_values[':time'] = completion_time
            
            self.tables['game_sessions'].update_item(
                Key={'session_id': session_id},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values
            )
            
        except Exception as e:
            print(f"Error completing game session: {e}")
            raise e

    def has_user_completed_daily_puzzle(self, discord_id: str, puzzle_date: str) -> bool:
        """Check if user has already completed today's puzzle"""
        try:
            session = self.get_user_game_session(discord_id, puzzle_date)
            return session and session.get('completed', False)
        except Exception as e:
            print(f"Error checking completion status: {e}")
            return False
    
    def _update_player_stats(self, discord_id: str, completion_time: int):
        """Update player statistics after completing a game"""
        try:
            # Get current player data
            response = self.tables['players'].get_item(
                Key={'discord_id': discord_id}
            )
            
            player = response.get('Item', {})
            current_best = player.get('best_time')
            
            # Prepare update expression
            update_expr = 'ADD total_games :one, games_won :one SET last_played = :last'
            expr_values = {
                ':one': 1,
                ':last': datetime.utcnow().isoformat()
            }
            
            # Update best time if this is better
            if current_best is None or completion_time < current_best:
                update_expr += ', best_time = :time'
                expr_values[':time'] = completion_time
            
            self.tables['players'].update_item(
                Key={'discord_id': discord_id},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values
            )
            
        except Exception as e:
            print(f"Error updating player stats: {e}")
    
    def _hash_group(self, words: List[str]) -> str:
        """Create hash for a group of words to check duplicates"""
        sorted_words = sorted([word.upper() for word in words])
        return hashlib.md5(''.join(sorted_words).encode()).hexdigest()
    

    def get_active_discord_channels(self) -> List[Dict[str, Any]]:
        """Get all active Discord channels for daily summary posting"""
        try:
            response = self.tables['discord_channels'].scan(
                FilterExpression='is_active = :active',
                ExpressionAttributeValues={':active': True}
            )
            
            return [self._convert_decimals(item) for item in response.get('Items', [])]
            
        except Exception as e:
            print(f"Error getting active Discord channels: {e}")
            return []
    
    def register_discord_channel(self, channel_id: str, guild_id: str, 
                                guild_name: str = None, channel_name: str = None) -> bool:
        """Register or update a Discord channel for daily summaries"""
        try:
            current_time = datetime.utcnow().isoformat()
            
            self.tables['discord_channels'].put_item(
                Item={
                    'channel_id': channel_id,
                    'guild_id': guild_id,
                    'guild_name': guild_name or 'Unknown Server',
                    'channel_name': channel_name or 'wordwebs',
                    'is_active': True,
                    'last_activity': current_time,
                    'created_at': current_time,
                    'settings': {
                        'daily_summary_enabled': True,
                        'summary_time': '00:05'  # 5 minutes after midnight EST
                    }
                }
            )
            return True
            
        except Exception as e:
            print(f"Error registering Discord channel: {e}")
            return False
    
    def update_channel_activity(self, channel_id: str) -> bool:
        """Update last activity timestamp for a Discord channel"""
        try:
            self.tables['discord_channels'].update_item(
                Key={'channel_id': channel_id},
                UpdateExpression='SET last_activity = :time',
                ExpressionAttributeValues={
                    ':time': datetime.utcnow().isoformat()
                }
            )
            return True
            
        except Exception as e:
            print(f"Error updating channel activity: {e}")
            return False
    
    def deactivate_discord_channel(self, channel_id: str) -> bool:
        """Deactivate a Discord channel (stop sending summaries)"""
        try:
            self.tables['discord_channels'].update_item(
                Key={'channel_id': channel_id},
                UpdateExpression='SET is_active = :active',
                ExpressionAttributeValues={':active': False}
            )
            return True
            
        except Exception as e:
            print(f"Error deactivating Discord channel: {e}")
            return False

    def _convert_decimals(self, obj):
        """Convert DynamoDB Decimals to regular numbers for JSON serialization"""
        if isinstance(obj, list):
            return [self._convert_decimals(i) for i in obj]
        elif isinstance(obj, dict):
            return {k: self._convert_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return obj