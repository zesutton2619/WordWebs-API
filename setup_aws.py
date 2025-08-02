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
        # Force use of Windows CMD instead of Git Bash
        if isinstance(cmd, str):
            # On Windows, explicitly use cmd.exe to avoid Git Bash conflicts
            if os.name == 'nt':
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, 
                                      executable=os.environ.get('SYSTEMROOT', 'C:\\Windows') + '\\System32\\cmd.exe')
            else:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        else:
            if os.name == 'nt':
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                      executable=os.environ.get('SYSTEMROOT', 'C:\\Windows') + '\\System32\\cmd.exe')
            else:
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

def wordwebs_lambda_functions_exist():
    """Check if WordWebs Lambda functions exist"""
    try:
        result = subprocess.run(
            ['aws', 'lambda', 'list-functions', '--output', 'json'],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            function_names = [f['FunctionName'] for f in data['Functions']]
            
            daily_exists = 'wordwebs-daily-puzzle-generator' in function_names
            api_exists = 'wordwebs-api-handler' in function_names
            
            return daily_exists and api_exists
        return False
    except Exception as e:
        print(f"Error checking functions: {e}")
        return False

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
    """Create DynamoDB tables from schema file"""
    print("Creating DynamoDB tables...")
    
    # Load schema from file
    schema_file = 'database/dynamodb_schema.json'
    if not os.path.exists(schema_file):
        print(f"ERROR: Schema file {schema_file} not found")
        return
        
    with open(schema_file, 'r') as f:
        schema = json.load(f)
    
    tables = schema['tables']
    
    for table_config in tables:
        table_name = table_config['TableName']
        
        # Check if table already exists
        cmd = ['aws', 'dynamodb', 'describe-table', '--table-name', table_name]
        if run_command(cmd):
            print(f"  Table {table_name} already exists")
            continue
        
        # Remove fields that aren't used in create-table and clean up empty arrays
        clean_config = {k: v for k, v in table_config.items() 
                       if k not in ['Description', 'ExampleItem']}
        
        # Remove empty arrays that cause AWS errors
        if 'GlobalSecondaryIndexes' in clean_config and not clean_config['GlobalSecondaryIndexes']:
            del clean_config['GlobalSecondaryIndexes']
        if 'LocalSecondaryIndexes' in clean_config and not clean_config['LocalSecondaryIndexes']:
            del clean_config['LocalSecondaryIndexes']
        
        # Create table using temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(clean_config, f)
            table_file = f.name
        
        try:
            cmd = ['aws', 'dynamodb', 'create-table', '--cli-input-json', f'file://{table_file}']
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
        # Create function with proper Windows path handling
        config_path = config_file.replace('\\', '/')
        zip_path = zip_file.replace('\\', '/')
        cmd = f'aws lambda create-function --cli-input-json file://{config_path} --zip-file fileb://{zip_path}'
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
        cors_path = cors_file.replace('\\', '/')
        cmd = f'aws lambda create-function-url-config --function-name {function_name} --auth-type NONE --cors file://{cors_path}'
        result = run_command(cmd, return_json=True)
        if result:
            # Add the critical permission for Function URL access
            print(f"Adding Function URL permission for: {function_name}")
            permission_cmd = f'aws lambda add-permission --function-name {function_name} --statement-id FunctionURLAllowPublicAccess --action lambda:invokeFunctionUrl --principal "*" --function-url-auth-type NONE'
            run_command(permission_cmd)
            return result.get('FunctionUrl')
        return None
    finally:
        if os.path.exists(cors_file):
            os.remove(cors_file)

def setup_eventbridge_rule(lambda_function_arn):
    """Create EventBridge rule for daily puzzle generation"""
    print("Creating EventBridge rule for daily puzzle generation...")
    
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

def setup_daily_summary_eventbridge(lambda_function_arn):
    """Create EventBridge rule for daily summary posting"""
    print("Creating EventBridge rule for daily summary posting...")
    
    # Create rule - 5 minutes after puzzle generation (12:05 AM EST)
    cmd = 'aws events put-rule --name wordwebs-daily-summary --schedule-expression "cron(5 5 * * ? *)" --description "Send daily summary at 12:05 AM EST"'
    run_command(cmd)
    
    # Add Lambda target
    account_id = get_account_id()
    targets = [{
        "Id": "1",
        "Arn": lambda_function_arn
    }]
    
    # Create targets file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(targets, f)
        targets_file = f.name
    
    try:
        cmd = f'aws events put-targets --rule wordwebs-daily-summary --targets file://{targets_file}'
        run_command(cmd)
        
        # Add permission for EventBridge to invoke Lambda
        cmd = f'aws lambda add-permission --function-name wordwebs-daily-summary-sender --statement-id allow-eventbridge-summary --action lambda:InvokeFunction --principal events.amazonaws.com --source-arn arn:aws:events:us-east-1:{account_id}:rule/wordwebs-daily-summary'
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
    
    required_vars = ['GEMINI_API_KEY', 'DISCORD_CLIENT_ID', 'DISCORD_CLIENT_SECRET', 'DISCORD_REDIRECT_URI']
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
    
    # Check if WordWebs Lambda functions already exist
    print("Checking for existing WordWebs Lambda functions...")
    if wordwebs_lambda_functions_exist():
        print("WordWebs Lambda functions already exist, skipping creation...")
        lambdas_need_creation = False
    else:
        print("WordWebs Lambda functions need to be created...")
        lambdas_need_creation = True
        
        # Check if deployment packages exist when we need to create functions
        daily_puzzle_zip = "lambda_functions/daily_puzzle_generator_deployment.zip"
        api_handler_zip = "lambda_functions/api_handler_deployment.zip"
        daily_summary_zip = "lambda_functions/daily_summary_sender_deployment.zip"
        
        if not os.path.exists(daily_puzzle_zip) or not os.path.exists(api_handler_zip) or not os.path.exists(daily_summary_zip):
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
    
    # Only create Lambda functions if they don't exist
    if lambdas_need_creation:
        # Prepare environment variables for Lambda
        daily_env = {
            "GEMINI_API_KEY": env_vars["GEMINI_API_KEY"]
        }
        
        api_env = {
            "DISCORD_CLIENT_ID": env_vars["DISCORD_CLIENT_ID"],
            "DISCORD_CLIENT_SECRET": env_vars["DISCORD_CLIENT_SECRET"],
            "DISCORD_REDIRECT_URI": env_vars["DISCORD_REDIRECT_URI"],
            "DISCORD_BOT_TOKEN": env_vars.get("DISCORD_BOT_TOKEN", "")
        }
        
        summary_env = {
            "DISCORD_BOT_TOKEN": env_vars.get("DISCORD_BOT_TOKEN", ""),
            "DISCORD_REDIRECT_URI": env_vars["DISCORD_REDIRECT_URI"]
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
        
        # Daily summary sender with Discord bot token
        daily_summary_zip = "lambda_functions/daily_summary_sender_deployment.zip"
        summary_result = create_lambda_function(
            "wordwebs-daily-summary-sender",
            "Daily summary posting to Discord channels",
            120, 256, daily_summary_zip, role_arn, summary_env
        )
    else:
        print("Skipping Lambda function creation - functions already exist")
    
    if lambdas_need_creation and daily_result and api_result and summary_result:
        print("Lambda functions created successfully")
    elif not lambdas_need_creation:
        print("Setup completed - DynamoDB tables recreated, Lambda functions already exist")
        
    # Set up EventBridge for daily puzzle generation (only if functions were created)
    if lambdas_need_creation and daily_result:
        setup_eventbridge_rule(daily_result['FunctionArn'])
        
    # Set up EventBridge for daily summary posting (only if functions were created)
    if lambdas_need_creation and summary_result:
        setup_daily_summary_eventbridge(summary_result['FunctionArn'])
        
    # Create Function URL for API handler (only if functions were created)
    if lambdas_need_creation and api_result:
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