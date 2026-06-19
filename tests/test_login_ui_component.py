"""
Unit tests for login page UI component functionality.

This module tests the login page UI component implementation for task 4.3,
focusing on UI rendering, error messages, and professional styling.

**Validates: Requirements 1.2, 1.3, 14.7**
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from io import StringIO

# NOTE: this previously inserted '.../src' onto sys.path and imported via
# `from components.authentication import ...` (no `src.` prefix), which made
# Python treat `components` as a top-level package. That breaks
# authentication.py's own `from ..core.database import db_manager` (a
# relative import that needs `components` to be a *subpackage* of `src`,
# not top-level) with "ImportError: attempted relative import beyond
# top-level package" -- it only "worked" before by accident, when an
# earlier-collected test file's `sys.modules['streamlit'] = Mock()` caused
# a different failure first and masked this one. Importing via the
# `src.components.authentication` path (matching every other test file)
# avoids the relative-import problem entirely.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestLoginUIComponent:
    """Unit tests for login page UI component functionality."""
    
    def test_render_login_page_function_exists(self):
        """Test that render_login_page function exists with correct signature."""
        from src.components.authentication import render_login_page
        
        # Check function exists
        assert callable(render_login_page), "render_login_page should be callable"
        
        # Check function has docstring with requirements validation
        assert render_login_page.__doc__ is not None, "Function should have docstring"
        assert "Requirements 1.2, 1.3, 14.7" in render_login_page.__doc__, \
            "Function should validate specified requirements"
    
    def test_session_manager_class_structure(self):
        """Test that SessionManager class has required methods."""
        from src.components.authentication import SessionManager
        
        # Check class exists
        assert SessionManager is not None, "SessionManager class should exist"
        
        # Check required methods exist
        required_methods = [
            'authenticate_user',
            'is_authenticated', 
            'get_session_info',
            'logout',
            'get_current_user_id'
        ]
        
        for method_name in required_methods:
            assert hasattr(SessionManager, method_name), \
                f"SessionManager should have {method_name} method"
            assert callable(getattr(SessionManager, method_name)), \
                f"{method_name} should be callable"
    
    def test_authentication_function_signature(self):
        """Test authenticate_user method has correct signature."""
        from src.components.authentication import SessionManager
        
        import inspect
        sig = inspect.signature(SessionManager.authenticate_user)
        
        # Should have self and passcode parameters
        params = list(sig.parameters.keys())
        assert 'self' in params, "Method should have self parameter"
        assert 'passcode' in params, "Method should have passcode parameter"
        
        # Should return bool
        assert sig.return_annotation == bool, "Method should return bool"
    
    def test_require_authentication_function_exists(self):
        """Test that require_authentication helper function exists."""
        from src.components.authentication import require_authentication
        
        assert callable(require_authentication), "require_authentication should be callable"
        
        # Check docstring mentions decorator functionality
        assert require_authentication.__doc__ is not None, "Function should have docstring"
    
    def test_session_info_rendering_function_exists(self):
        """Test that session info rendering function exists."""
        from src.components.authentication import render_session_info
        
        assert callable(render_session_info), "render_session_info should be callable"
    
    def test_user_creation_utility_exists(self):
        """Test that user creation utility function exists."""
        from src.components.authentication import create_user_with_passcode
        
        assert callable(create_user_with_passcode), "create_user_with_passcode should be callable"
        
        import inspect
        sig = inspect.signature(create_user_with_passcode)
        
        # Should have passcode parameter and return bool
        assert 'passcode' in sig.parameters, "Function should have passcode parameter" 
        assert sig.return_annotation == bool, "Function should return bool"
    
    @patch('streamlit.title')
    @patch('streamlit.markdown') 
    @patch('streamlit.form')
    @patch('streamlit.text_input')
    @patch('streamlit.form_submit_button')
    def test_login_page_ui_structure(self, mock_submit, mock_input, mock_form, 
                                   mock_markdown, mock_title):
        """Test that login page renders expected UI elements."""
        from src.components.authentication import render_login_page
        
        # Mock Streamlit form context manager
        mock_form.return_value.__enter__ = Mock()
        mock_form.return_value.__exit__ = Mock()
        
        # Mock form submission with no passcode
        mock_input.return_value = ""
        mock_submit.return_value = True
        
        # Mock error function
        with patch('streamlit.error') as mock_error:
            result = render_login_page()
            
            # Should return False when no passcode provided
            assert result is False, "Should return False for empty passcode"
            
            # Should call error display
            mock_error.assert_called()
    
    def test_enhanced_styling_elements_present(self):
        """Test that enterprise styling elements are present in the code.

        The login page was redesigned to a compact, centered card (per an
        explicit "make it enterprise level, not lengthy" request): CSS class
        names moved from ad-hoc `login-*` classes defined inline to the
        shared `gcc-login-*` classes in `src/utils/theme.py`, and width is
        now constrained via a real `st.columns(...)` layout rather than a
        non-functional custom `<div>` wrapper.
        """
        from src.components.authentication import render_login_page

        import inspect
        source = inspect.getsource(render_login_page)

        # Check for key styling/layout elements of the new design
        styling_elements = [
            'gcc-login-wrap',
            'gcc-login-logo',
            'gcc-login-title',
            'gcc-login-chip-row',
            'st.columns',
            'clean_html',
        ]

        found_elements = [elem for elem in styling_elements if elem in source]

        # Should have most styling elements
        assert len(found_elements) >= 4, \
            f"Should have at least 4 styling elements, found: {found_elements}"
    
    def test_error_message_handling_present(self):
        """Test that error message handling is present."""
        from src.components.authentication import render_login_page

        import inspect
        source = inspect.getsource(render_login_page)

        # Check for clear, distinct error messages covering each failure mode
        error_elements = [
            'Please enter your passcode',
            'Incorrect passcode',
            'system error',
            'st.error',
        ]

        found_errors = [elem for elem in error_elements if elem in source]

        # Should have comprehensive error handling
        assert len(found_errors) >= 3, \
            f"Should have comprehensive error handling, found: {found_errors}"
    
    def test_user_feedback_mechanisms_present(self):
        """Test that user feedback mechanisms are implemented."""
        from src.components.authentication import render_login_page

        import inspect
        source = inspect.getsource(render_login_page)

        # Check for user feedback elements
        feedback_elements = [
            'st.spinner',
            'Verifying credentials',
            'st.success',
            'Authenticated',
            'time.sleep',
        ]

        found_feedback = [elem for elem in feedback_elements if elem in source]

        # Should have user feedback mechanisms
        assert len(found_feedback) >= 3, \
            f"Should have user feedback mechanisms, found: {found_feedback}"
    
    def test_professional_styling_css_structure(self):
        """Test that the login page's CSS is centrally themed.

        Styling now lives in the shared `src/utils/theme.py` module (one
        `<style>` block reused by every page, including
        `[data-testid="stForm"]` rules that style the login card, the
        sidebar, KPI cards, etc.) rather than being redefined inline inside
        `render_login_page` itself -- that centralization is the whole
        point of the enterprise theme module.
        """
        from src.utils import theme
        import inspect

        css_source = inspect.getsource(theme)

        css_elements = [
            'gcc-login-logo',
            'border-radius',
            'box-shadow',
            'color:',
            'font-size',
            'margin',
            'padding',
        ]

        found_css = [elem for elem in css_elements if elem in css_source]

        assert len(found_css) >= 5, \
            f"Should have professional CSS styling, found: {found_css}"
    
    def test_help_information_section_present(self):
        """Test that help/capability information is present.

        The old wide two-column "Platform Capabilities" / "Need Access?"
        boxes were replaced with a compact chip row plus a one-line
        footnote, per the explicit "not lengthy" redesign request -- the
        same information is conveyed far more compactly.
        """
        from src.components.authentication import render_login_page

        import inspect
        source = inspect.getsource(render_login_page)

        help_elements = [
            'CSV Upload',
            'AI-Powered Research',
            'system administrator',
            'gcc-login-chip',
            'gcc-login-footnote',
        ]

        found_help = [elem for elem in help_elements if elem in source]

        assert len(found_help) >= 3, \
            f"Should have help information section, found: {found_help}"
    
    def test_security_note_present(self):
        """Test that security and privacy information is present."""
        from src.components.authentication import render_login_page

        import inspect
        source = inspect.getsource(render_login_page)

        # Check for security elements (case-insensitive: wording was
        # condensed into a single footnote line during the redesign)
        security_elements = [
            'encrypted',
            'expire',
            '24h',
            'administrator',
        ]

        found_security = [elem for elem in security_elements if elem in source.lower()]

        # Should have security information
        assert len(found_security) >= 3, \
            f"Should have security information, found: {found_security}"
    
    def test_custom_css_injection(self):
        """Test that the shared enterprise CSS theme covers the login page.

        CSS injection was centralized: `main.py` calls
        `inject_enterprise_theme()` once per page render (so every page,
        login included, shares one `<style>` block) instead of each page
        re-injecting its own ad-hoc `<style>` tag. Verify the shared theme
        actually contains the `<style>` block and the login-specific rules.
        """
        from src.utils.theme import _THEME_CSS, inject_enterprise_theme

        assert callable(inject_enterprise_theme), "inject_enterprise_theme should be callable"
        assert '<style>' in _THEME_CSS, "Shared theme should inject CSS via a <style> block"
        assert 'gcc-login' in _THEME_CSS, "Shared theme should include login page styling"


class TestAuthenticationIntegration:
    """Integration tests for authentication UI and logic."""
    
    def test_authentication_imports_successfully(self):
        """Test that all authentication components import without errors."""
        # This tests the module structure without requiring Streamlit
        try:
            from src.components import authentication
            assert hasattr(authentication, 'render_login_page')
            assert hasattr(authentication, 'SessionManager') 
            assert hasattr(authentication, 'require_authentication')
            assert hasattr(authentication, 'render_session_info')
        except ImportError as e:
            # Expected if Streamlit is not available, but structure should be correct
            assert 'streamlit' in str(e).lower(), f"Unexpected import error: {e}"
    
    def test_task_requirements_validation(self):
        """Test that the implementation validates the specified task requirements."""
        from src.components.authentication import render_login_page
        
        docstring = render_login_page.__doc__
        assert docstring is not None, "Function should have docstring"
        
        # Check for requirement validation
        assert "Requirements 1.2, 1.3, 14.7" in docstring, \
            "Should validate Requirements 1.2, 1.3, 14.7"
        
        # Check that docstring describes the UI design (updated for the
        # compact/centered enterprise redesign)
        expected_descriptions = [
            "centered",
            "enterprise",
            "st.columns",
        ]

        assert any(desc in docstring.lower() for desc in expected_descriptions), \
            "Docstring should describe the login page's UI design"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])