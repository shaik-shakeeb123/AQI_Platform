import React, { useState, useEffect, startTransition } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "../context/AuthContext";
import "./Sidebar.css";

// Icons
import HomeOutlinedIcon from '@mui/icons-material/HomeOutlined';
import WarningAmberOutlinedIcon from '@mui/icons-material/WarningAmberOutlined';
import MapOutlinedIcon from '@mui/icons-material/MapOutlined';
import RouteOutlinedIcon from '@mui/icons-material/RouteOutlined';
import NotificationsOutlinedIcon from '@mui/icons-material/NotificationsOutlined';
import PersonOutlineOutlinedIcon from '@mui/icons-material/PersonOutlineOutlined';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import LogoutOutlinedIcon from '@mui/icons-material/LogoutOutlined';
import PushPinOutlinedIcon from '@mui/icons-material/PushPinOutlined';
import PushPinIcon from '@mui/icons-material/PushPin';
import MenuIcon from '@mui/icons-material/Menu';
import KeyboardDoubleArrowLeftIcon from '@mui/icons-material/KeyboardDoubleArrowLeft';

const NAV_ITEMS = [
    { id: "dashboard", label: "Dashboard", icon: HomeOutlinedIcon },
    { id: "alerts", label: "Alerts", icon: WarningAmberOutlinedIcon },
    { id: "heatmap", label: "Heatmap", icon: MapOutlinedIcon },
    { id: "route", label: "Route Planner", icon: RouteOutlinedIcon },
    { id: "notifications", label: "Notifications", icon: NotificationsOutlinedIcon },
    { id: "profile", label: "Profile", icon: PersonOutlineOutlinedIcon },
    { id: "settings", label: "Settings", icon: SettingsOutlinedIcon },
];

function Sidebar({ page, setPage }) {
    const { logout: authLogout } = useAuth();
    
    // State initialization from localStorage
    const [isPinned, setIsPinned] = useState(() => {
        const saved = localStorage.getItem("sidebarPinned");
        return saved !== null ? saved === "true" : true;
    });
    
    const [isExpanded, setIsExpanded] = useState(() => {
        const saved = localStorage.getItem("sidebarExpanded");
        return saved !== null ? saved === "true" : true;
    });
    
    const [isHovered, setIsHovered] = useState(false);
    const [isMobile, setIsMobile] = useState(false);
    const [mobileOpen, setMobileOpen] = useState(false);

    // Update global CSS variables for layout shifts
    useEffect(() => {
        const updateLayout = () => {
            if (window.innerWidth <= 900) {
                setIsMobile(true);
                document.documentElement.style.setProperty('--sidebar-width', '0px');
            } else {
                setIsMobile(false);
                if (!isPinned) {
                    document.documentElement.style.setProperty('--sidebar-width', '0px');
                } else {
                    document.documentElement.style.setProperty('--sidebar-width', isExpanded ? '280px' : '72px');
                }
            }
        };

        updateLayout();
        window.addEventListener("resize", updateLayout);
        return () => window.removeEventListener("resize", updateLayout);
    }, [isPinned, isExpanded]);

    // Save preferences
    useEffect(() => {
        localStorage.setItem("sidebarPinned", isPinned);
        localStorage.setItem("sidebarExpanded", isExpanded);
    }, [isPinned, isExpanded]);

    // Keyboard Shortcut (Ctrl+B)
    useEffect(() => {
        const handleKeyDown = (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
                e.preventDefault();
                setIsExpanded(prev => !prev);
                setIsPinned(true); // Auto-pin when using keyboard toggle for visibility
            }
        };
        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, []);

    const handleLogout = async () => {
        try {
            await authLogout();
            alert("Logged Out Successfully");
        } catch(err) {
            console.log(err);
            alert(err.message);
        }
    };

    const handleNavClick = (id) => {
        startTransition(() => {
            setPage(id);
        });
        if (isMobile) {
            setMobileOpen(false);
        }
    };

    // Determine visual state
    const showExpandedUI = isMobile ? true : (isPinned ? isExpanded : isHovered);
    const sidebarWidth = showExpandedUI ? 280 : (isPinned ? 72 : 0);

    return (
        <>
            {/* Mobile Hamburger Button */}
            {isMobile && (
                <button 
                    className="mobile-toggle" 
                    onClick={() => setMobileOpen(true)}
                    aria-label="Open Navigation"
                >
                    <MenuIcon />
                </button>
            )}

            {/* Mobile Overlay */}
            {isMobile && mobileOpen && (
                <div 
                    className="sidebar-overlay" 
                    onClick={() => setMobileOpen(false)} 
                />
            )}

            {/* Hover Trigger Area for Unpinned Mode */}
            {!isMobile && !isPinned && !isHovered && (
                <div 
                    className="sidebar-hover-trigger" 
                    onMouseEnter={() => setIsHovered(true)}
                />
            )}

            <motion.nav 
                className={`sidebar ${isPinned ? "pinned" : "floating"} ${isMobile ? "mobile" : ""}`}
                initial={false}
                animate={{
                    width: isMobile ? 280 : sidebarWidth,
                    x: isMobile ? (mobileOpen ? 0 : "-100%") : (!isPinned && !isHovered ? "-100%" : 0),
                    boxShadow: (isHovered || isMobile) ? "4px 0 25px rgba(0,0,0,0.4)" : "1px 0 0 rgba(255,255,255,0.05)"
                }}
                transition={{ type: "spring", stiffness: 300, damping: 30 }}
                onMouseEnter={() => !isPinned && setIsHovered(true)}
                onMouseLeave={() => !isPinned && setIsHovered(false)}
            >
                {/* Header / Logo */}
                <div className="sidebar-header">
                    <div className="logo-container">
                        <motion.span className="logo-icon" layout>🌿</motion.span>
                        <AnimatePresence mode="popLayout">
                            {showExpandedUI && (
                                <motion.div 
                                    className="logo-text"
                                    initial={{ opacity: 0, x: -10 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    exit={{ opacity: 0, x: -10 }}
                                    transition={{ duration: 0.2 }}
                                >
                                    <h2>AQI</h2>
                                    <span>Insight Pro</span>
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>

                    {!isMobile && (
                        <div className="sidebar-controls">
                            <button 
                                className="control-btn"
                                onClick={() => setIsPinned(!isPinned)}
                                aria-label={isPinned ? "Unpin sidebar" : "Pin sidebar"}
                                title={isPinned ? "Unpin sidebar" : "Pin sidebar"}
                            >
                                {isPinned ? <PushPinIcon fontSize="small"/> : <PushPinOutlinedIcon fontSize="small"/>}
                            </button>
                            {isPinned && (
                                <button 
                                    className="control-btn toggle-collapse"
                                    onClick={() => setIsExpanded(!isExpanded)}
                                    aria-label="Toggle sidebar"
                                    title="Toggle Sidebar (Ctrl+B)"
                                    style={{ transform: isExpanded ? 'rotate(0deg)' : 'rotate(180deg)' }}
                                >
                                    <KeyboardDoubleArrowLeftIcon fontSize="small"/>
                                </button>
                            )}
                        </div>
                    )}
                </div>

                {/* Nav Items */}
                <ul className="sidebar-nav">
                    {NAV_ITEMS.map((item) => {
                        const Icon = item.icon;
                        const isActive = page === item.id;

                        return (
                            <li key={item.id} className={`nav-item ${isActive ? "active" : ""}`}>
                                <button 
                                    onClick={() => handleNavClick(item.id)}
                                    className="nav-btn"
                                    aria-label={item.label}
                                >
                                    <div className="nav-icon-wrapper">
                                        <Icon className="nav-icon" />
                                        {isActive && <motion.div layoutId="active-indicator" className="active-indicator" />}
                                    </div>
                                    
                                    <AnimatePresence mode="popLayout">
                                        {showExpandedUI && (
                                            <motion.span 
                                                className="nav-label"
                                                initial={{ opacity: 0, x: -10 }}
                                                animate={{ opacity: 1, x: 0 }}
                                                exit={{ opacity: 0, x: -10 }}
                                                transition={{ duration: 0.2 }}
                                            >
                                                {item.label}
                                            </motion.span>
                                        )}
                                    </AnimatePresence>

                                    {/* Tooltip for collapsed state */}
                                    {!showExpandedUI && (
                                        <div className="nav-tooltip">{item.label}</div>
                                    )}
                                </button>
                            </li>
                        );
                    })}
                </ul>

                {/* Footer */}
                <div className="sidebar-footer">
                    <li className="nav-item logout">
                        <button onClick={handleLogout} className="nav-btn" aria-label="Logout">
                            <div className="nav-icon-wrapper">
                                <LogoutOutlinedIcon className="nav-icon" />
                            </div>
                            <AnimatePresence mode="popLayout">
                                {showExpandedUI && (
                                    <motion.span 
                                        className="nav-label"
                                        initial={{ opacity: 0 }}
                                        animate={{ opacity: 1 }}
                                        exit={{ opacity: 0 }}
                                        transition={{ duration: 0.2 }}
                                    >
                                        Logout
                                    </motion.span>
                                )}
                            </AnimatePresence>
                            {!showExpandedUI && (
                                <div className="nav-tooltip logout-tooltip">Logout</div>
                            )}
                        </button>
                    </li>
                </div>
            </motion.nav>
        </>
    );
}

export default Sidebar;