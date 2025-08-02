import sys
import os
sys.path.append('/opt')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
import pytz
from shared.dynamodb_client import DynamoDBClient


def lambda_handler(event, context):
    """
    Lambda function triggered daily at midnight EST to generate the day's puzzle.
    Can also be triggered manually via EventBridge or API Gateway.
    """
    
    try:
        # Get current date in EST
        est = pytz.timezone('US/Eastern')
        current_date = datetime.now(est).strftime('%Y-%m-%d')
        
        db = DynamoDBClient()
        
        # Check if puzzle already exists for today
        existing_puzzle = db.get_daily_puzzle(current_date)
        if existing_puzzle:
            return {
                'statusCode': 200,
                'body': {
                    'message': f'Puzzle already exists for {current_date}',
                    'puzzle_id': existing_puzzle['puzzle_id']
                }
            }
        
        # Generate new puzzle
        from shared.puzzle_generator import PuzzleGenerator
        generator = PuzzleGenerator()
        
        # Try up to 5 times to generate a non-duplicate puzzle
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                puzzle_data = generator.generate_puzzle(db_client=db)
                
                # Check for duplicate groups in historical data
                if not db.check_duplicate_groups(puzzle_data['groups']):
                    break
                
                if attempt == max_attempts - 1:
                    # If all attempts had duplicates, allow the last one
                    # (Better to have some duplication than no puzzle)
                    print(f"Warning: Generated puzzle may have duplicate groups after {max_attempts} attempts")
                    
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise e
                continue
        
        # Save daily puzzle
        puzzle_id = db.save_daily_puzzle(
            current_date, 
            puzzle_data['words'], 
            puzzle_data['groups']
        )
        
        # Save to historical puzzles for duplicate checking
        db.save_historical_puzzle(puzzle_data['groups'])
        
        return {
            'statusCode': 200,
            'body': {
                'message': f'Successfully generated puzzle for {current_date}',
                'puzzle_id': puzzle_id,
                'word_count': len(puzzle_data['words']),
                'groups': len(puzzle_data['groups'])
            }
        }
        
    except Exception as e:
        print(f"Error generating daily puzzle: {str(e)}")
        return {
            'statusCode': 500,
            'body': {
                'error': f'Failed to generate daily puzzle: {str(e)}'
            }
        }

# For local testing
if __name__ == "__main__":
    # Mock event and context for testing
    test_event = {}
    test_context = {}
    
    result = lambda_handler(test_event, test_context)
    print(result)