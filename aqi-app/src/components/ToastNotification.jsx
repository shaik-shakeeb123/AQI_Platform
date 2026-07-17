import React, { useEffect } from "react";
import "./ToastNotification.css";

function ToastNotification({

    notification,

    onClose

}) {

    useEffect(() => {

        if (!notification) return;

        const timer = setTimeout(() => {

            onClose();

        }, 5000);

        return () => clearTimeout(timer);

    }, [notification, onClose]);

    if (!notification) return null;

    return (

        <div className={`toast ${notification.type}`}>

            <div className="toast-icon">

                {notification.icon}

            </div>

            <div className="toast-body">

                <h3>{notification.title}</h3>

                <p>{notification.message}</p>

            </div>

            <button

                className="toast-close"

                onClick={onClose}

            >

                ✕

            </button>

        </div>

    );

}

export default ToastNotification;