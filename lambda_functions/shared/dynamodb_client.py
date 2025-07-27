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
            'theme_suggestions': self.dynamodb.Table('wordwebs-theme-suggestions')
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
    
    def save_game_session(self, discord_id: str, display_name: str, puzzle_date: str, 
                         puzzle_id: str, guesses: List[List[str]], completed: bool, 
                         completion_time: Optional[int] = None) -> str:
        """Save game session and update player stats"""
        session_id = str(uuid.uuid4())
        
        # Save game session
        session_item = {
            'session_id': session_id,
            'discord_id': discord_id,
            'display_name': display_name,
            'puzzle_date': puzzle_date,
            'puzzle_id': puzzle_id,
            'guesses': guesses,
            'completed': completed,
            'created_at': datetime.utcnow().isoformat()
        }
        
        if completion_time is not None:
            session_item['completion_time'] = completion_time
        
        self.tables['game_sessions'].put_item(Item=session_item)
        
        # Update player stats
        if completed and completion_time is not None:
            self._update_player_stats(discord_id, completion_time)
        else:
            # Just increment total games
            self.tables['players'].update_item(
                Key={'discord_id': discord_id},
                UpdateExpression='ADD total_games :one SET last_played = :last',
                ExpressionAttributeValues={
                    ':one': 1,
                    ':last': datetime.utcnow().isoformat()
                }
            )
        
        return session_id
    
    def get_daily_leaderboard(self, date: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get daily leaderboard sorted by completion time"""
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
    

    def _convert_decimals(self, obj):
        """Convert DynamoDB Decimals to regular numbers for JSON serialization"""
        if isinstance(obj, list):
            return [self._convert_decimals(i) for i in obj]
        elif isinstance(obj, dict):
            return {k: self._convert_decimals(v) for k, v in obj.items()}
        elif isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return obj