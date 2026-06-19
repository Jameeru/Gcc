# 🔐 Authentication Guide

## Understanding the Two Systems

Your GCC platform now has **two separate authentication systems**:

### 1. 👤 **Admin Panel** (`streamlit run admin.py`)
- **Purpose:** User management and system administration
- **Users:** Admin accounts stored in `admin_users` table
- **Default Login:** `admin@gcc.com` / `Admin123!`
- **Features:** Create/edit/delete regular users, reset passwords, system settings

### 2. 🏢 **Main Application** (`streamlit run main.py`)
- **Purpose:** GCC research and data processing
- **Users:** Regular users stored in `users` table
- **Authentication Options:**
  - Email & Password (new)
  - Legacy Passcode (existing)
- **Features:** CSV upload, AI research, results export

## 🚨 Common Issues & Solutions

### Issue: "Authentication failed for admin@gcc.com" in main app
**Cause:** You're trying to use admin credentials in the main application.
**Solution:** Admin credentials only work in the admin panel. Create a regular user for the main app.

### Issue: KeyError 'src.core'
**Cause:** Streamlit logging configuration issue (harmless).
**Solution:** This is a warning that doesn't affect functionality. The app works normally.

### Issue: No users to test with
**Solution:** Use the user creation utility or admin panel to create users.

## 🛠️ Quick Setup Guide

### Step 1: Create Your First Regular User
```bash
# Option A: Use the creation utility
python3 create_user.py testuser@gmail.com TestPass123! "Test User"

# Option B: Use the admin panel
streamlit run admin.py
# Login with admin@gcc.com / Admin123!
# Go to "Create User" tab
```

### Step 2: Test Main Application
```bash
streamlit run main.py
# Choose "Email & Password"
# Login with the user you created
```

### Step 3: Test Admin Panel
```bash
streamlit run admin.py
# Login with admin@gcc.com / Admin123!
```

## 📋 Available User Accounts

### Pre-created Test Users (Main App)
- `newuser@gmail.com` / `NewPassword123!`
- `testmain@gcc.com` / `TestMain123!`

### Admin Account (Admin Panel)
- `admin@gcc.com` / `Admin123!` ⚠️ **Change this password!**

## 🎯 Authentication Flow Examples

### Main Application Login Options

#### Option 1: Email & Password (Recommended)
1. Run `streamlit run main.py`
2. Select "Email & Password" 
3. Enter email and password
4. Access full GCC platform features

#### Option 2: Legacy Passcode
1. Run `streamlit run main.py`
2. Select "Passcode Only"
3. Enter existing passcode
4. Maintains backward compatibility

### Admin Panel Access
1. Run `streamlit run admin.py`
2. Login with admin email/password
3. Manage users and system settings

## 🔧 User Management Workflow

### Creating Regular Users (for Main App)
1. **Via Admin Panel:**
   - Login to admin panel
   - Go to "Create User" tab
   - Fill form and submit

2. **Via Command Line:**
   ```bash
   python3 create_user.py email@domain.com Password123! "Full Name"
   ```

### Managing Existing Users
- **View Users:** Admin Panel → User Management
- **Edit Users:** Click "Edit" button
- **Reset Passwords:** Click "Reset Password" button
- **Deactivate Users:** Click "Deactivate" button

## 🔒 Security Best Practices

### Password Requirements
- Minimum 8 characters
- Uppercase letter (A-Z)
- Lowercase letter (a-z)
- Number (0-9)
- Special character (!@#$%^&*())

### Admin Security
1. **Change default admin password immediately**
2. Use strong passwords for all accounts
3. Monitor user activity through admin panel
4. Regular security reviews

### User Security
1. Forgot password functionality available
2. Password reset via secure tokens
3. Rate limiting prevents abuse
4. Audit logging tracks access

## 📞 Troubleshooting

### Authentication Not Working?
1. **Check which app you're using:**
   - Admin credentials → Admin panel only
   - Regular user credentials → Main app only

2. **Verify user exists:**
   - Check admin panel user list
   - Use command line utility to create users

3. **Check password strength:**
   - Must meet all security requirements
   - Case-sensitive passwords

### Can't Access Admin Panel?
1. Ensure using correct credentials: `admin@gcc.com` / `Admin123!`
2. Run `streamlit run admin.py` (not main.py)
3. Check database connectivity

### Forgot Password Not Working?
1. Feature works for main app users only
2. Email service needs configuration for production
3. Check console logs for reset links in development

## 🚀 Quick Commands Reference

```bash
# Create user for main app
python3 create_user.py user@email.com Pass123! "Name"

# Launch main application  
streamlit run main.py

# Launch admin panel
streamlit run admin.py

# Test authentication
python3 test_authentication_enhancements.py
```

## 💡 Tips

1. **Use admin panel** to manage all regular users
2. **Test with multiple browsers** to verify different user sessions
3. **Monitor logs** for authentication issues
4. **Regular backups** of user data through admin panel
5. **Keep admin credentials secure** and change defaults

---

**Remember:** Admin panel manages the main app users. The two systems work together but have separate login credentials!