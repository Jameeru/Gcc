#!/usr/bin/env python3
"""
Test script to verify all imports from theme.py work correctly.
"""

def test_theme_imports():
    """Test that all theme imports work."""
    try:
        from src.utils.theme import ACCENT_RED, clean_html, inject_enterprise_theme, kpi_card, pill, render_page_header
        print("✅ All imports successful!")
        print(f"ACCENT_RED = {ACCENT_RED}")
        print(f"clean_html function = {clean_html}")
        print(f"inject_enterprise_theme function = {inject_enterprise_theme}")
        print(f"kpi_card function = {kpi_card}")
        print(f"pill function = {pill}")
        print(f"render_page_header function = {render_page_header}")
        
        # Test clean_html function
        test_html = "  <div>  \n  test  \n  </div>  "
        cleaned = clean_html(test_html)
        print(f"clean_html test: '{cleaned}'")
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    test_theme_imports()