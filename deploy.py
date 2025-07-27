#!/usr/bin/env python3
"""
Simple deployment script for WordWebs Lambda functions
Usage: python deploy.py [function_name]
"""

import os
import sys
import subprocess
import zipfile
import shutil
import tempfile
from pathlib import Path

# Configuration
LAMBDA_FUNCTIONS = {
    'daily_puzzle_generator': {
        'function_name': 'wordwebs-daily-puzzle-generator',
        'description': 'Daily puzzle generation for WordWebs',
        'timeout': 300,
        'memory': 512
    },
    'api_handler': {
        'function_name': 'wordwebs-api-handler', 
        'description': 'API handler for WordWebs Discord Activity',
        'timeout': 30,
        'memory': 256
    }
}

def run_command(cmd, cwd=None):
    """Run shell command and return output"""
    try:
        # On Windows, split command properly to avoid bash issues
        if os.name == 'nt' and isinstance(cmd, str):  # Windows
            cmd_parts = cmd.split()
            result = subprocess.run(cmd_parts, cwd=cwd, capture_output=True, text=True)
        else:
            result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Error running command: {cmd}")
            print(f"Error: {result.stderr}")
            return False
        return result.stdout.strip()
    except Exception as e:
        print(f"Exception running command: {cmd}")
        print(f"Error: {e}")
        return False

def create_deployment_package(function_dir):
    """Create deployment package for Lambda function"""
    print(f"Creating deployment package for {function_dir}...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Copy function code
        shutil.copytree(function_dir, os.path.join(temp_dir, 'function'))
        
        # Copy shared code
        shared_dir = Path(__file__).parent / 'lambda_functions' / 'shared'
        shutil.copytree(shared_dir, os.path.join(temp_dir, 'function', 'shared'))
        
        # Install dependencies
        requirements_file = os.path.join(temp_dir, 'function', 'requirements.txt')
        if os.path.exists(requirements_file):
            print("Installing dependencies...")
            target_dir = os.path.join(temp_dir, 'function')
            if os.name == 'nt':  # Windows - install for Lambda Linux x86_64 architecture  
                cmd = ['pip', 'install', '-r', requirements_file, '--target', target_dir, 
                       '--platform', 'manylinux2014_x86_64', '--only-binary=:all:', '--upgrade']
                try:
                    # Override pip config that forces --user
                    env = os.environ.copy()
                    env['PIP_USER'] = 'false'
                    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
                    if result.returncode != 0:
                        print(f"Error installing dependencies: {result.stderr}")
                        return None
                except Exception as e:
                    print(f"Exception installing dependencies: {e}")
                    return None
            else:
                cmd = f'pip install -r "{requirements_file}" -t "{target_dir}"'
                if not run_command(cmd):
                    return None
        
        # Create zip file
        zip_path = os.path.join(temp_dir, 'deployment.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            function_path = os.path.join(temp_dir, 'function')
            for root, dirs, files in os.walk(function_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, function_path)
                    zipf.write(file_path, arcname)
        
        # Copy to final location
        final_zip_path = f"{function_dir}_deployment.zip"
        shutil.copy2(zip_path, final_zip_path)
        return final_zip_path

def check_aws_cli():
    """Check if AWS CLI is installed and configured"""
    if not run_command('aws --version'):
        print("ERROR: AWS CLI is not installed or not in PATH")
        print("Please install AWS CLI and configure it with 'aws configure'")
        return False
    
    if not run_command('aws sts get-caller-identity'):
        print("ERROR: AWS CLI is not configured")
        print("Please run 'aws configure' to set up your credentials")
        return False
    
    print("AWS CLI is configured")
    return True

def lambda_function_exists(function_name):
    """Check if Lambda function exists"""
    cmd = f'aws lambda get-function --function-name {function_name}'
    return run_command(cmd) is not False

def create_lambda_function(config, zip_file):
    """Create new Lambda function"""
    function_name = config['function_name']
    print(f"Creating Lambda function: {function_name}")
    
    cmd = f'''aws lambda create-function \
        --function-name {function_name} \
        --runtime python3.11 \
        --role arn:aws:iam::ACCOUNT_ID:role/lambda-execution-role \
        --handler lambda_function.lambda_handler \
        --zip-file fileb://{zip_file} \
        --description "{config['description']}" \
        --timeout {config['timeout']} \
        --memory-size {config['memory']}'''
    
    return run_command(cmd)

def update_lambda_function(function_name, zip_file):
    """Update existing Lambda function"""
    print(f"Updating Lambda function: {function_name}")
    
    if os.name == 'nt':  # Windows - use list format
        cmd = ['aws', 'lambda', 'update-function-code', '--function-name', function_name, '--zip-file', f'fileb://{zip_file}']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error updating function: {result.stderr}")
                return False
            return result.stdout.strip()
        except Exception as e:
            print(f"Exception updating function: {e}")
            return False
    else:
        cmd = f'aws lambda update-function-code --function-name {function_name} --zip-file "fileb://{zip_file}"'
        return run_command(cmd)

def deploy_function(function_key):
    """Deploy a specific Lambda function"""
    if function_key not in LAMBDA_FUNCTIONS:
        print(f"ERROR: Unknown function: {function_key}")
        print(f"Available functions: {', '.join(LAMBDA_FUNCTIONS.keys())}")
        return False
    
    config = LAMBDA_FUNCTIONS[function_key]
    function_dir = Path(__file__).parent / 'lambda_functions' / function_key
    
    if not function_dir.exists():
        print(f"ERROR: Function directory not found: {function_dir}")
        return False
    
    # Create deployment package
    zip_file = create_deployment_package(str(function_dir))
    if not zip_file:
        print("ERROR: Failed to create deployment package")
        return False
    
    # Update or create function
    function_name = config['function_name']
    if lambda_function_exists(function_name):
        result = update_lambda_function(function_name, zip_file)
        if result is not False:
            print(f"Successfully deployed {function_name}")
            # Clean up zip file after successful deployment
            if os.path.exists(zip_file):
                os.remove(zip_file)
            return True
        else:
            print(f"ERROR: Failed to deploy {function_name}")
            return False
    else:
        print(f"Deployment package created: {zip_file}")
        print(f"Function {function_name} doesn't exist yet - run setup_aws.py to create it")
        return True

def main():
    """Main deployment function"""
    if not check_aws_cli():
        return
    
    if len(sys.argv) > 1:
        # Deploy specific function
        function_name = sys.argv[1]
        deploy_function(function_name)
    else:
        # Deploy all functions
        print("Deploying all Lambda functions...")
        for function_key in LAMBDA_FUNCTIONS:
            print(f"\n--- Deploying {function_key} ---")
            deploy_function(function_key)

if __name__ == "__main__":
    main()