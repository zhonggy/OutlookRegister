"""GUI 页面。"""

from .about import AboutView
from .dashboard import DashboardView
from .register import RegisterView
from .settings import SettingsView

__all__ = ["DashboardView", "RegisterView", "SettingsView", "AboutView"]
