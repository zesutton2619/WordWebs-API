# WordWebs API - Always-Free Serverless Backend

Serverless backend for the WordWebs Discord Activity using AWS Lambda, DynamoDB, and Gemini AI. **Completely free forever** using AWS Always Free Tier.

## Prerequisites

- AWS Account created
- Gemini API key obtained from [Google AI Studio](https://aistudio.google.com/app/apikey)
- Python 3.11+ installed

## Quick Setup Guide

### 1. Install AWS CLI and Configure Credentials
```bash
# Download and install AWS CLI from: https://aws.amazon.com/cli/
# After installation, configure your credentials:
aws configure
```
You'll need:
- AWS Access Key ID
- AWS Secret Access Key  
- Default region (recommend: us-east-1)
- Default output format: json

Test with: `aws sts get-caller-identity`

### 2. Set Up Environment Variables
```bash
# Copy the example file
copy .env.example .env

# Edit .env and add your Gemini API key:
GEMINI_API_KEY=your-actual-gemini-api-key-here
```

### 3. Deploy Everything to AWS
```bash
# This creates DynamoDB tables, Lambda functions, and Function URLs
python setup_aws.py
```

### 4. Get Your API URL
The setup script will show your Function URL:
```
API URL: https://abc123xyz.lambda-url.us-east-1.on.aws/
```

### 5. Test Your Deployment
- Test the API URL in browser: `https://your-url.lambda-url.us-east-1.on.aws/`
- Should see: `{"message": "WordWebs API is running"}`
- Test daily puzzle endpoint: `https://your-url.lambda-url.us-east-1.on.aws/daily-puzzle`

### 6. Update Your Frontend
Use the Function URL in your Discord Activity frontend code.

## Daily Development

```bash
# Deploy all functions
python deploy.py

# Deploy specific function
python deploy.py daily_puzzle_generator
python deploy.py api_handler
```

## Troubleshooting

If something fails:
- Check AWS credentials: `aws sts get-caller-identity`
- Verify Gemini API key in .env file
- Check Python version: `python --version` (should be 3.11+)
- Re-run the failed step

## AWS Resources Created

After successful deployment, you'll have:
- 5 DynamoDB tables (wordwebs-*)
- 2 Lambda functions
- 1 Lambda Function URL (your API endpoint)
- 1 EventBridge rule (daily puzzle generation at midnight EST)
- 1 IAM role (Lambda execution)

Everything stays within AWS Always Free Tier limits!

## Always-Free Architecture

```
Discord Activity Frontend
          ↓
Lambda Function URL (HTTPS)
          ↓
Lambda Functions
          ↓
DynamoDB Tables
```

**Always Free Components:**
- **Lambda**: 1M requests + 400,000 GB-seconds/month
- **DynamoDB**: 25 GB storage + 200M requests/month
- **Lambda Function URLs**: FREE (included with Lambda)
- **EventBridge**: 14M events/month

## Project Structure

```
lambda_functions/
├── shared/                    # Shared code for both functions
│   ├── dynamodb_client.py    # DynamoDB operations
│   └── puzzle_generator.py   # Gemini AI integration
├── daily_puzzle_generator/   # Scheduled daily puzzle creation
│   ├── lambda_function.py
│   └── requirements.txt
└── api_handler/              # API endpoints for frontend
    ├── lambda_function.py
    └── requirements.txt

database/
└── dynamodb_schema.json     # DynamoDB table definitions

deploy.py                    # Create deployment packages
setup_aws.py                # One-time AWS deployment
quick_deploy.bat            # Windows shortcut
```

## Environment Variables (.env file)

```bash
# Gemini AI Configuration
GEMINI_API_KEY=your-gemini-api-key-here
```

**Security Note:** Never commit `.env` to git! It's already in `.gitignore`.

## API Endpoints

Your Lambda Function URL provides these endpoints:

- `GET /daily-puzzle` - Get today's puzzle
- `POST /submit-guess` - Submit player guess
- `GET /leaderboard?date=YYYY-MM-DD` - Get leaderboard
- `GET /player-stats?discord_id=ID` - Get player stats

Example: `https://your-function-url.lambda-url.us-east-1.on.aws/daily-puzzle`

## Database

DynamoDB tables created automatically:
- `wordwebs-daily-puzzles` - Current day's puzzle
- `wordwebs-players` - Discord player info
- `wordwebs-game-sessions` - Game attempts and leaderboard data
- `wordwebs-historical-puzzles` - Prevent duplicate groups
- `wordwebs-theme-suggestions` - For future voting feature

## Development Workflow

1. **Make code changes** in `lambda_functions/`
2. **Deploy instantly:** `python deploy.py [function_name]`
3. **Test immediately** - no manual zip uploads!

## Features

- **Daily Auto-Generation**: Puzzles created at midnight EST via EventBridge
- **Duplicate Prevention**: Checks historical puzzles to avoid repeated groups
- **Discord Integration**: Player tracking with Discord IDs
- **Leaderboards**: Daily and all-time statistics
- **Theme Support**: Ready for community voting system
- **Always Free**: No ongoing AWS costs within free tier limits

## AWS Costs

**Stays within Always Free Tier:**
- Lambda: 1M requests/month free (forever)
- DynamoDB: 25 GB + 200M requests/month free (forever)
- Lambda Function URLs: FREE (forever)
- EventBridge: 14M events/month free (forever)

**Estimated Discord Activity Usage:**
- 1000 daily players = ~30K Lambda requests/month
- Puzzle data storage = ~1 MB total
- Well within all free tier limits!

## Troubleshooting

**Deploy fails?**
- Check AWS credentials: `aws sts get-caller-identity`
- Verify function exists: `aws lambda get-function --function-name wordwebs-api-handler`

**Function URL not working?**
- Check CORS configuration in setup script
- Verify Lambda function has Function URL enabled

**DynamoDB errors?**
- Check IAM permissions include DynamoDB access
- Verify tables were created: `aws dynamodb list-tables`

## Advantages Over Previous Architecture

**Before (PostgreSQL + API Gateway):**
- RDS PostgreSQL: $13-15/month after 12 months
- API Gateway: $1-3.50 per million requests
- VPC complexity for database access

**Now (DynamoDB + Function URLs):**
- DynamoDB: FREE forever (25GB limit)
- Function URLs: FREE forever
- No VPC configuration needed
- Simpler deployment and maintenance

## Frontend Integration

Update your Discord Activity frontend to use the Lambda Function URL:

```javascript
const API_BASE_URL = 'https://your-function-url.lambda-url.us-east-1.on.aws';

// Example API calls
const puzzle = await fetch(`${API_BASE_URL}/daily-puzzle`);
const response = await fetch(`${API_BASE_URL}/submit-guess`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ discord_id, guess, puzzle_id })
});
```

No API keys or authentication needed - the Function URL is public and CORS-enabled.

## Features

- **Daily Auto-Generation**: New puzzles created at midnight EST via EventBridge
- **NYT Connections Style**: Tricky word groupings with red herrings and misdirection
- **Duplicate Prevention**: Checks historical puzzles to avoid repeated word groups
- **Discord Integration**: Player tracking with Discord IDs
- **Leaderboards**: Daily and all-time statistics
- **Always Free**: No ongoing AWS costs within free tier limits