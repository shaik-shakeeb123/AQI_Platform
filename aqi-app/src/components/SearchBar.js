import React, { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cities } from "../data/indianCities";
import "./SearchBar.css";

import SearchOutlinedIcon from '@mui/icons-material/SearchOutlined';
import CloseOutlinedIcon from '@mui/icons-material/CloseOutlined';
import LocationCityOutlinedIcon from '@mui/icons-material/LocationCityOutlined';
import AutorenewIcon from '@mui/icons-material/Autorenew';

function SearchBar({ onSearch, isLoading }) {
    const [city, setCity] = useState("");
    const [isFocused, setIsFocused] = useState(false);
    const [suggestions, setSuggestions] = useState([]);
    const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(-1);
    const [errorMsg, setErrorMsg] = useState("");
    
    const wrapperRef = useRef(null);

    // Close dropdown on click outside
    useEffect(() => {
        function handleClickOutside(event) {
            if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
                setIsFocused(false);
            }
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

    const validateInput = (input) => {
        if (!input.trim()) return "Please enter a city name.";
        if (/^\d+$/.test(input.trim())) return "City name cannot be numeric.";
        return "";
    };

    const handleSearch = (searchCity = city) => {
        const validationError = validateInput(searchCity);
        if (validationError) {
            setErrorMsg(validationError);
            return;
        }
        setErrorMsg("");
        setIsFocused(false);
        onSearch(searchCity);
    };

    const handleChange = (e) => {
        const val = e.target.value;
        setCity(val);
        setErrorMsg("");
        
        // Filter suggestions
        if (val.trim().length > 0) {
            const filtered = cities
                .filter(c => c.name.toLowerCase().startsWith(val.toLowerCase()))
                .slice(0, 5); // Max 5 suggestions
            setSuggestions(filtered);
            setActiveSuggestionIndex(-1);
        } else {
            setSuggestions([]);
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            if (activeSuggestionIndex >= 0 && activeSuggestionIndex < suggestions.length) {
                const selected = suggestions[activeSuggestionIndex].name;
                setCity(selected);
                handleSearch(selected);
            } else {
                handleSearch();
            }
        } else if (e.key === "ArrowDown") {
            e.preventDefault();
            if (suggestions.length > 0) {
                setActiveSuggestionIndex(prev => 
                    prev < suggestions.length - 1 ? prev + 1 : 0
                );
            }
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            if (suggestions.length > 0) {
                setActiveSuggestionIndex(prev => 
                    prev > 0 ? prev - 1 : suggestions.length - 1
                );
            }
        } else if (e.key === "Escape") {
            setIsFocused(false);
        }
    };

    const handleSuggestionClick = (selectedCity) => {
        setCity(selectedCity);
        handleSearch(selectedCity);
    };

    const clearInput = () => {
        setCity("");
        setSuggestions([]);
        setErrorMsg("");
        // Retain focus
        const inputElement = wrapperRef.current.querySelector('input');
        if (inputElement) inputElement.focus();
    };

    return (
        <div className="search-container" ref={wrapperRef}>
            <div className="search-flex">
                
                {/* Input Wrapper */}
                <div className={`search-input-wrapper ${isFocused ? 'focused' : ''} ${errorMsg ? 'error' : ''}`}>
                    <SearchOutlinedIcon className="search-icon-glass" />
                    <input
                        type="text"
                        className="search-input"
                        placeholder="Search for a city..."
                        value={city}
                        onChange={handleChange}
                        onKeyDown={handleKeyDown}
                        onFocus={() => setIsFocused(true)}
                        aria-label="Search for a city"
                        role="searchbox"
                    />
                    
                    <AnimatePresence>
                        {city.length > 0 && (
                            <motion.button
                                initial={{ opacity: 0, scale: 0.8 }}
                                animate={{ opacity: 1, scale: 1 }}
                                exit={{ opacity: 0, scale: 0.8 }}
                                onClick={clearInput}
                                className="clear-btn"
                                aria-label="Clear search"
                                type="button"
                            >
                                <CloseOutlinedIcon fontSize="small" />
                            </motion.button>
                        )}
                    </AnimatePresence>
                </div>

                {/* Submit Button */}
                <button
                    className="search-btn-glass"
                    onClick={() => handleSearch(city)}
                    disabled={isLoading}
                >
                    {isLoading ? (
                        <>
                            <AutorenewIcon className="spinner-icon" />
                            Searching...
                        </>
                    ) : (
                        "Check AQI"
                    )}
                </button>
            </div>

            {/* Error Message */}
            <AnimatePresence>
                {errorMsg && (
                    <motion.div 
                        className="error-msg"
                        initial={{ opacity: 0, y: -5 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -5 }}
                    >
                        {errorMsg}
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Suggestions Dropdown */}
            <AnimatePresence>
                {isFocused && suggestions.length > 0 && (
                    <motion.ul 
                        className="search-dropdown"
                        initial={{ opacity: 0, y: 10, scale: 0.98 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 10, scale: 0.98 }}
                        transition={{ type: "spring", stiffness: 300, damping: 30 }}
                        role="listbox"
                    >
                        {suggestions.map((suggestion, index) => (
                            <li 
                                key={suggestion.name}
                                className={`search-dropdown-item ${index === activeSuggestionIndex ? 'active' : ''}`}
                                onClick={() => handleSuggestionClick(suggestion.name)}
                                onMouseEnter={() => setActiveSuggestionIndex(index)}
                                role="option"
                                aria-selected={index === activeSuggestionIndex}
                            >
                                <LocationCityOutlinedIcon fontSize="small" className="search-dropdown-icon" />
                                {suggestion.name}
                            </li>
                        ))}
                    </motion.ul>
                )}
            </AnimatePresence>
        </div>
    );
}

export default SearchBar;