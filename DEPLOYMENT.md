# GCC Research Intelligence Platform - Deployment Guide

## Streamlit Cloud Deployment

### Prerequisites

1. **GitHub Repository**: Push this code to a GitHub repository
2. **Supabase Account**: Set up your database at https://supabase.com
3. **OpenAI API Key**: Get your API key from https://platform.openai.com
4. **Gemini API Key** (Optional): Get your API key from Google AI Studio

### Step-by-Step Deployment

#### 1. Set Up Supabase Database

1. Create a new Supabase project
2. Go to Settings > Database and note your connection details
3. Run the database setup:
   ```bash
   python setup_database.py
   ```
4. Your current Supabase URL: `https://nkkmdzphiwmowwzzqqwx.supabase.co`
5. You need the **service role key** (not the public key) for full access

#### 2. Push to GitHub

1. Create a new GitHub repository
2. Push this code to the repository:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: GCC Research Intelligence Platform"
   git remote add origin https://github.com/yourusername/gcc-research-platform.git
   git push -u origin main
   ```

#### 3. Deploy to Streamlit Cloud

1. Go to https://share.streamlit.io
2. Click "New app"
3. Connect your GitHub repository
4. Set the main file path to: `main.py`
5. Click "Advanced settings"

#### 4. Configure Secrets

In Streamlit Cloud's "Secrets" section, paste the content from `secrets.toml.template`:

```toml
# Replace with your actual values
SUPABASE_URL = "https://nkkmdzphiwmowwzzqqwx.supabase.co"
SUPABASE_KEY = "your-service-role-key-here"
OPENAI_API_KEY = "sk-your-openai-api-key-here"
GEMINI_API_KEY_1 = "AIza-your-gemini-api-key-here"
SETTINGS_ENCRYPTION_KEY = "GRQpNGNA2N0ELul0FjQDEGl9KEQHRWlAZ27Fjrn4v4I="

# ... (see secrets.toml.template for all settings)
```

#### 5. Deploy!

Click "Deploy" and wait for the application to build and start.

### Important Notes

- **Service Role Key**: Make sure you use the Supabase service role key, not the public key
- **Encryption Key**: Use the generated key: `GRQpNGNA2N0ELul0FjQDEGl9KEQHRWlAZ27Fjrn4v4I=`
- **First User**: The first user will need to be added to the database manually or through the setup script
- **API Keys**: Both OpenAI and Gemini keys can be managed through the app's Settings tab after deployment

### Troubleshooting

1. **Database Connection Issues**: Verify your Supabase URL and service role key
2. **Import Errors**: Check that all dependencies are in requirements.txt
3. **Permission Errors**: Ensure the service role key has full database access
4. **Environment Variables**: Verify all secrets are properly configured in Streamlit Cloud

### Security

- Never commit actual API keys to the repository
- Use Streamlit Cloud's secrets management
- The platform includes encryption for API keys stored in the database
- All authentication is handled securely with bcrypt password hashing

### Monitoring

After deployment, monitor:
- Application logs in Streamlit Cloud dashboard
- Database usage in Supabase dashboard  
- API usage in OpenAI/Gemini dashboards
- Processing session metrics in the app's Dashboard tab