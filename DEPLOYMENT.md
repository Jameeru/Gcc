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
6. **Get the connection-pooler URI** (required for Streamlit Cloud): go to
   Settings > Database > Connection Pooling, select "Session pooler", and
   copy the URI. It looks like:
   `postgresql://postgres.<project_ref>:<db-password>@aws-0-<region>.pooler.supabase.com:5432/postgres`
   This is the value you'll set as `DATABASE_URL` in step 4 below. Supabase's
   *direct* connection host (`db.<ref>.supabase.co`) resolves to an
   IPv6-only address on most projects, and Streamlit Community Cloud has no
   IPv6 egress -- using it produces exactly this error:
   `could not translate host name "db.<ref>.supabase.co" to address: No
   address associated with hostname`. The pooler host is IPv4-compatible and
   avoids this entirely.

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
# Replace with your actual values. DATABASE_URL is the recommended path --
# it bypasses the IPv6/hardcoded-password issues entirely (see step 1.6).
DATABASE_URL = "postgresql://postgres.<project_ref>:<db-password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
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

- **DATABASE_URL is the recommended way to configure the database** on
  Streamlit Cloud. Use the Session/Transaction pooler URI from Supabase's
  Connection Pooling page, not the direct `db.<ref>.supabase.co` host.
- **Service Role Key**: Make sure you use the Supabase service role key, not the public key. Note this key authenticates the Supabase *API*, not Postgres directly -- it cannot be used as a database password.
- **Encryption Key**: Use the generated key: `GRQpNGNA2N0ELul0FjQDEGl9KEQHRWlAZ27Fjrn4v4I=`
- **First User**: The first user will need to be added to the database manually or through the setup script
- **API Keys**: Both OpenAI and Gemini keys can be managed through the app's Settings tab after deployment

### Troubleshooting

1. **Database Connection Issues** -- "could not translate host name ... to address: No address associated with hostname": this means the app is using the direct Supabase host, which is IPv6-only on most projects and unreachable from Streamlit Community Cloud (no IPv6 egress). Fix: set `DATABASE_URL` in Streamlit Cloud's Secrets to the pooler URI from Supabase's Settings > Database > Connection Pooling page, then reboot the app.
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