#!/usr/bin/env python3
"""
GCC Research Intelligence Platform - Admin Panel

Standalone admin panel for user management with email/password authentication.
Run with: streamlit run admin.py
"""

import os
import sys

# Add the current directory to the path so we can import from src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import and run the admin panel
from src.components.admin_panel import main_admin_panel

if __name__ == "__main__":
    main_admin_panel()