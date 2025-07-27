#!/usr/bin/env python3
"""
One-time setup script for WordWebs AWS infrastructure
This creates the Lambda functions, DynamoDB tables, and Function URLs
"""

import subprocess
import json
import sys
import os
import tempfile
from pathlib import Path

def run_command(cmd, return_json=False):
    """Run AWS CLI command"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            return None
        if return_json:
            return json.loads(result.stdout)
        return result.stdout.strip()
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_account_id():
    """Get AWS account ID"""
    result = run_command('aws sts get-caller-identity', return_json=True)
    return result['Account'] if result else None

def create_lambda_execution_role():
    """Create IAM role for Lambda functions"""
    print("Creating Lambda execution role...")
    
    # Create trust policy file
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(trust_policy, f)
        trust_policy_file = f.name
    
    try:
        # Create role
        cmd = f'aws iam create-role --role-name wordwebs-lambda-execution-role --assume-role-policy-document file://{trust_policy_file} --description "Execution role for WordWebs Lambda functions"'
        result = run_command(cmd, return_json=True)
        if not result:
            print("Role might already exist, continuing...")
        
        # Attach basic execution policy
        cmd = 'aws iam attach-role-policy --role-name wordwebs-lambda-execution-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
        run_command(cmd)
        
        # Attach DynamoDB execution policy
        cmd = 'aws iam attach-role-policy --role-name wordwebs-lambda-execution-role --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess'
        run_command(cmd)
        
        account_id = get_account_id()
        return f"arn:aws:iam::{account_id}:role/wordwebs-lambda-execution-role"
        
    finally:
        # Clean up temp file
        if os.path.exists(trust_policy_file):
            os.remove(trust_policy_file)

def create_dynamodb_tables():
    """Create DynamoDB tables"""
    print("Creating DynamoDB tables...")
    
    tables = [
        {
            'TableName': 'wordwebs-daily-puzzles',
            'KeySchema': [{'AttributeName': 'puzzle_date', 'KeyType': 'HASH'}],
            'AttributeDefinitions': [{'AttributeName': 'puzzle_date', 'AttributeType': 'S'}],
            'BillingMode': 'PAY_PER_REQUEST'
        },
        {
            'TableName': 'wordwebs-players',
            'KeySchema': [{'AttributeName': 'discord_id', 'KeyType': 'HASH'}],
            'AttributeDefinitions': [{'AttributeName': 'discord_id', 'AttributeType': 'S'}],
            'BillingMode': 'PAY_PER_REQUEST'
        },
        {
            'TableName': 'wordwebs-game-sessions',
            'KeySchema': [{'AttributeName': 'session_id', 'KeyType': 'HASH'}],
            'AttributeDefinitions': [
                {'AttributeName': 'session_id', 'AttributeType': 'S'},
                {'AttributeName': 'puzzle_date', 'AttributeType': 'S'},
                {'AttributeName': 'completion_time', 'AttributeType': 'N'}
            ],
            'BillingMode': 'PAY_PER_REQUEST',
            'GlobalSecondaryIndexes': [{
                'IndexName': 'puzzle-date-time-index',
                'KeySchema': [
                    {'AttributeName': 'puzzle_date', 'KeyType': 'HASH'},
                    {'AttributeName': 'completion_time', 'KeyType': 'RANGE'}
                ],
                'Projection': {'ProjectionType': 'ALL'}
            }]
        },
        {
            'TableName': 'wordwebs-historical-puzzles',
            'KeySchema': [{'AttributeName': 'group_hash', 'KeyType': 'HASH'}],
            'AttributeDefinitions': [{'AttributeName': 'group_hash', 'AttributeType': 'S'}],
            'BillingMode': 'PAY_PER_REQUEST'
        },
        {
            'TableName': 'wordwebs-theme-suggestions',
            'KeySchema': [{'AttributeName': 'theme_id', 'KeyType': 'HASH'}],
            'AttributeDefinitions': [
                {'AttributeName': 'theme_id', 'AttributeType': 'S'},
                {'AttributeName': 'status', 'AttributeType': 'S'}
            ],
            'BillingMode': 'PAY_PER_REQUEST',
            'GlobalSecondaryIndexes': [{
                'IndexName': 'status-index',
                'KeySchema': [{'AttributeName': 'status', 'KeyType': 'HASH'}],
                'Projection': {'ProjectionType': 'ALL'}
            }]
        }
    ]
    
    for table_config in tables:
        table_name = table_config['TableName']
        
        # Check if table already exists
        cmd = f'aws dynamodb describe-table --table-name {table_name}'
        if run_command(cmd):
            print(f"  Table {table_name} already exists")
            continue
        
        # Create table using temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(table_config, f)
            table_file = f.name
        
        try:
            cmd = f'aws dynamodb create-table --cli-input-json file://{table_file}'
            result = run_command(cmd, return_json=True)
            if result:
                print(f"  Created table: {table_name}")
            else:
                print(f"  Failed to create table: {table_name}")
        finally:
            if os.path.exists(table_file):
                os.remove(table_file)
    
    print("Waiting for tables to become active...")
    import time
    time.sleep(10)

def create_lambda_function(name, description, timeout, memory, zip_file, role_arn, env_vars=None):
    """Create Lambda function"""
    print(f"Creating Lambda function: {name}")
    
    function_config = {
        "FunctionName": name,
        "Runtime": "python3.11",
        "Role": role_arn,
        "Handler": "lambda_function.lambda_handler",
        "Description": description,
        "Timeout": timeout,
        "MemorySize": memory
    }
    
    if env_vars:
        function_config["Environment"] = {"Variables": env_vars}
    
    # Create function config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(function_config, f)
        config_file = f.name
    
    try:
        # Create function
        cmd = f'aws lambda create-function --cli-input-json file://{config_file} --zip-file fileb://{zip_file}'
        result = run_command(cmd, return_json=True)
        return result
    finally:
        if os.path.exists(config_file):
            os.remove(config_file)

def create_function_url(function_name):
    """Create Lambda Function URL"""
    print(f"Creating Function URL for: {function_name}")
    
    cors_config = {
        "AllowCredentials": False,
        "AllowHeaders": ["*"],
        "AllowMethods": ["*"],
        "AllowOrigins": ["*"],
        "ExposeHeaders": ["*"],
        "MaxAge": 86400
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(cors_config, f)
        cors_file = f.name
    
    try:
        cmd = f'aws lambda create-function-url-config --function-name {function_name} --auth-type NONE --cors file://{cors_file}'
        result = run_command(cmd, return_json=True)
        if result:
            return result.get('FunctionUrl')
        return None
    finally:
        if os.path.exists(cors_file):
            os.remove(cors_file)

def setup_eventbridge_rule(lambda_function_arn):
    """Create EventBridge rule for daily puzzle generation"""
    print("Creating EventBridge rule...")
    
    # Create rule
    cmd = 'aws events put-rule --name wordwebs-daily-puzzle --schedule-expression "cron(0 5 * * ? *)" --description "Generate daily puzzle at midnight EST"'
    run_command(cmd)
    
    # Add Lambda target
    account_id = get_account_id()
    targets = [{
        "Id": "1",
        "Arn": lambda_function_arn
    }]
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(targets, f)
        targets_file = f.name
    
    try:
        cmd = f'aws events put-targets --rule wordwebs-daily-puzzle --targets file://{targets_file}'
        run_command(cmd)
        
        # Add permission for EventBridge to invoke Lambda
        cmd = f'aws lambda add-permission --function-name wordwebs-daily-puzzle-generator --statement-id allow-eventbridge --action lambda:InvokeFunction --principal events.amazonaws.com --source-arn arn:aws:events:us-east-1:{account_id}:rule/wordwebs-daily-puzzle'
        run_command(cmd)
    finally:
        if os.path.exists(targets_file):
            os.remove(targets_file)

def load_env_vars():
    """Load environment variables from .env file"""
    env_file = Path(__file__).parent / '.env'
    
    if not env_file.exists():
        print("ERROR: .env file not found!")
        print("Please copy .env.example to .env and fill in your values")
        return None
    
    env_vars = {}
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    
    required_vars = ['GEMINI_API_KEY', 'DISCORD_CLIENT_ID', 'DISCORD_CLIENT_SECRET']
    missing_vars = [var for var in required_vars if not env_vars.get(var)]
    
    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file")
        return None
    
    return env_vars

def main():
    """Main setup function"""
    print("Setting up WordWebs AWS infrastructure...")
    
    # Load environment variables
    env_vars = load_env_vars()
    if not env_vars:
        return
    
    # Check if deployment packages exist
    daily_puzzle_zip = "lambda_functions/daily_puzzle_generator_deployment.zip"
    api_handler_zip = "lambda_functions/api_handler_deployment.zip"
    
    if not os.path.exists(daily_puzzle_zip) or not os.path.exists(api_handler_zip):
        print("ERROR: Deployment packages not found. Run 'python deploy.py' first to create them.")
        return
    
    # Create IAM role
    role_arn = create_lambda_execution_role()
    if not role_arn:
        print("ERROR: Failed to create execution role")
        return
    
    print("Waiting for role to propagate...")
    import time
    time.sleep(10)
    
    # Create DynamoDB tables
    create_dynamodb_tables()
    
    # Prepare environment variables for Lambda
    daily_env = {
        "GEMINI_API_KEY": env_vars["GEMINI_API_KEY"]
    }
    
    api_env = {
        "DISCORD_CLIENT_ID": env_vars["DISCORD_CLIENT_ID"],
        "DISCORD_CLIENT_SECRET": env_vars["DISCORD_CLIENT_SECRET"]
    }
    
    daily_result = create_lambda_function(
        "wordwebs-daily-puzzle-generator",
        "Daily puzzle generation for WordWebs",
        300, 512, daily_puzzle_zip, role_arn, daily_env
    )
    
    # API handler with Discord OAuth environment variables
    api_result = create_lambda_function(
        "wordwebs-api-handler",
        "API handler for WordWebs Discord Activity", 
        30, 256, api_handler_zip, role_arn, api_env
    )
    
    if daily_result and api_result:
        print("Lambda functions created successfully")
        
        # Set up EventBridge for daily puzzle generation
        setup_eventbridge_rule(daily_result['FunctionArn'])
        
        # Create Function URL for API handler
        api_url = create_function_url("wordwebs-api-handler")
        
        print("\nSetup complete!")
        print(f"\nAPI URL: {api_url}")
        print("\nEndpoints:")
        print(f"  GET  {api_url}daily-puzzle")
        print(f"  POST {api_url}submit-guess")
        print(f"  GET  {api_url}leaderboard")
        print(f"  GET  {api_url}player-stats")
        print(f"  POST {api_url}discord-oauth/token")
        print(f"  POST {api_url}discord-oauth/refresh")
        print(f"  GET  {api_url}discord-oauth/verify")
        print("\nNext steps:")
        print("1. Update your frontend to use the new API URL")
        print("2. Test endpoints")
        print("3. Use 'python deploy.py' to update Lambda functions")
    
    else:
        print("ERROR: Failed to create Lambda functions")

if __name__ == "__main__":
    main()