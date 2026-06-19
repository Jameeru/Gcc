# 👤 GCC Admin Panel

A comprehensive admin panel for managing users and system settings in the GCC Research Intelligence Platform.

## 🚀 Quick Start

### Launch Admin Panel
```bash
streamlit run admin.py
```

### Default Admin Login
- **Email:** `admin@gcc.com`
- **Password:** `Admin123!`

⚠️ **Important:** Change the default password after first login!

## ✨ Features

### 🔐 Admin Authentication
- Secure email/password authentication
- Session management with 2-hour timeout
- Role-based access control
- Automatic admin account creation

### 👥 User Management
- **Create Users:** Add new users with email, password, and full name
- **Edit Users:** Update user information and status
- **Password Reset:** Reset passwords for any user
- **User Status:** Activate/deactivate user accounts
- **User Search:** Find users by email or name
- **Delete Users:** Soft delete with confirmation

### 📊 Dashboard & Analytics
- User statistics and KPIs
- Recent activity monitoring
- System health indicators
- Database metrics

### 🔧 System Administration
- Database cleanup tools
- Expired token management
- System configuration
- Admin profile management

## 🎯 User Authentication Options

The platform now supports **dual authentication methods**:

### 1. Email & Password (New)
- Modern email/password authentication
- Strong password requirements
- Password reset functionality
- User profile management

### 2. Legacy Passcode (Existing)
- Backward compatibility maintained
- Simple passcode-based access
- No profile information required

## 📋 User Management Workflow

### Creating a New User
1. Go to **"Create User"** tab
2. Enter user details:
   - Email address
   - Full name
   - Strong password
3. Click **"Create User"**
4. User can now login with email/password

### Managing Existing Users
1. Go to **"User Management"** tab
2. Find user in the list
3. Use action buttons:
   - **Edit:** Change email, name, or status
   - **Reset Password:** Set new password
   - **Activate/Deactivate:** Toggle user access
   - **Delete:** Remove user (soft delete)

### Password Requirements
- Minimum 8 characters
- At least one uppercase letter (A-Z)
- At least one lowercase letter (a-z)
- At least one number (0-9)
- At least one special character (!@#$%^&*())

## 🔒 Security Features

### Password Security
- Bcrypt hashing with salt
- Password strength validation
- Password history tracking
- Reuse prevention

### Session Security
- Secure session tokens
- Automatic timeout (2 hours for admin)
- Session invalidation on logout
- Activity logging

### Rate Limiting
- Password reset attempt limits
- Failed login protection
- Audit trail maintenance

## 🛠️ Database Schema

The admin panel automatically creates the following tables:

- **admin_users:** Administrator accounts
- **users:** Enhanced with email and full_name columns
- **password_reset_tokens:** Secure reset functionality
- **reset_rate_limits:** Anti-abuse protection
- **password_reset_audit_log:** Security monitoring

## 📱 User Interface

### Dashboard View
- Clean, modern interface
- KPI cards with user statistics
- Quick action buttons
- Real-time data updates

### User Management
- Searchable user list
- Status indicators (Active/Inactive pills)
- Modal dialogs for operations
- Bulk operations support

### Forms & Validation
- Real-time input validation
- Clear error messages
- Password strength indicators
- Confirmation dialogs

## 🔧 Configuration

### Environment Variables
The admin panel uses the same environment configuration as the main application:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
DATABASE_URL=your_database_url
SETTINGS_ENCRYPTION_KEY=your_encryption_key
```

### Default Settings
- Admin session timeout: 2 hours
- Password reset token expiry: 30 minutes
- Rate limit: 3 attempts per hour
- Auto-cleanup: Expired tokens

## 🚨 Important Notes

### Security Considerations
1. **Change default admin password immediately**
2. Use strong passwords for all accounts
3. Monitor admin access logs regularly
4. Keep the system updated

### Production Deployment
1. Use HTTPS for admin panel access
2. Implement IP whitelisting if needed
3. Set up regular database backups
4. Configure email service for password resets

### Maintenance
- Regular cleanup of expired tokens
- Monitor user activity logs
- Review admin access patterns
- Update security policies as needed

## 📞 Support

For technical support or questions about the admin panel:
1. Check the application logs for error details
2. Review the database connection settings
3. Verify environment variable configuration
4. Contact your system administrator

## 🎉 Getting Started Checklist

- [ ] Launch admin panel: `streamlit run admin.py`
- [ ] Login with default credentials
- [ ] Change default admin password
- [ ] Create your first user account
- [ ] Test email/password authentication
- [ ] Configure password reset functionality
- [ ] Set up regular maintenance schedule

---

**Admin Panel Version:** Latest  
**Compatibility:** GCC Research Intelligence Platform v2.0+  
**Security Level:** Production Ready ✅