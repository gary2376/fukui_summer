You're asking me to provide an English description of the Fukui Emergency Preparedness System project. Based on the codebase context, this is a comprehensive disaster response and preparedness platform designed for Fukui Prefecture, Japan.

# Fukui Emergency Preparedness System Project Overview

## Project Summary

The Fukui Emergency Preparedness System is a comprehensive disaster response and preparedness platform specifically designed for Fukui Prefecture, Japan. The system provides both proactive disaster preparedness tools and real-time emergency response capabilities, integrating shelter mapping, contact management, emergency notifications, and intelligent route planning.

## System Architecture

### Three-Tier Web Application Architecture

The system implements a three-tier web application architecture with Flask serving as the central orchestrator between frontend interfaces, backend services, and data storage layers. 

<img width="1266" height="573" alt="截圖 2025-08-26 03 54 48" src="https://github.com/user-attachments/assets/3ebb0f52-5efb-4402-bb74-d98fa336d416" />


## Core Functional Modules

### 1. Emergency Mode and Shelter Mapping

The system provides two operational modes: normal mode and emergency mode. 

**Emergency Mode Features:**
- Virtual GPS Simulation: Generates realistic location data through `get_virtual_gps_location()` function
- Disaster Type Assignment: Randomly selects appropriate disaster scenarios
- Intelligent Route Planning: Integrates OSMnx for real-world path calculation

### 2. Flood Path Obstacle Avoidance System

This is the system's core technical feature, implementing dynamic disaster route planning. 

**Technical Features:**
- Real-time Water Level Data Integration: Parses CSV format water level data
- Intelligent Risk Assessment: Automatically detects areas with excessive water levels
- Dynamic Route Avoidance: Adjusts road network weights to avoid dangerous areas

### 3. Emergency Kit Management System

Provides disaster-type-based emergency supply management functionality.

**Functional Features:**
- Disaster-Specific Recommendations: Provides specialized item lists for different disasters like earthquakes, floods, and fires
- Item Category Management: Organized by protective equipment, medical supplies, food and water categories
- Store Integration: Finds nearby stores through Google Places API 

### 4. Personal Health and Diet Information Management

Uses SQLite database to manage personal health profiles.

**Database Structure:**
- `diet_info` table: Basic personal information and emergency contacts
- `allergies` table: Food allergy information with severity levels
- `preferences` table: Dietary preference settings

**Interface Features:**
- Allergy Management: Supports mild, moderate, severe, and fatal severity classifications
- Emergency Information: Emergency medication and medical notes management

## Data Architecture

### Hybrid Data Architecture

The system employs a hybrid architecture combining relational databases with CSV files:

**Database Components:**
- `shelters.db`: Shelter information including coordinates, names, and disaster type flags
- `avoid_zone.db`: Hazard area polygons for route planning obstacle avoidance
- `diet_card.db`: Personal health profiles

**CSV Data Sources:**
- `fukui_水位.csv`: Real-time water level monitoring data 
- `contacts.csv`: Emergency contact information
- `fukui_trans.csv`: Traffic restrictions and construction zones

## External Service Integration

### API Integration

The system integrates multiple external services to provide comprehensive functionality:

- **Google Maps API**: Map visualization through Folium integration
- **Google Places API**: Nearby store location services
- **OpenAI API**: Real-time Japanese translation functionality
- **OSMnx/OpenStreetMap**: Road network data and pathfinding algorithms

### Authentication Support

Supports multiple email providers for emergency notifications:
- Gmail: App password authentication
- Outlook: Standard credential authentication
- SendGrid: API-based bulk email service

## Emergency Response Workflow

Complete workflow during disaster scenarios:

<img width="975" height="744" alt="截圖 2025-08-26 03 57 24" src="https://github.com/user-attachments/assets/17d75c0d-0152-4533-a928-24824b51d72b" />


## Technical Dependencies and Deployment

### Main Technology Stack

- **Python 3.8+**: Primary programming language
- **Flask**: Web application framework
- **OSMnx**: Road network data and route planning
- **Folium**: Map visualization
- **SQLite**: Database operations
- **Pandas**: Data processing

### System Startup

```bash
cd fukui_summer/code
python app.py
```

## Emergency Notification System

The system provides immediate communication capabilities through integrated email and SMS notification systems.Users can send emergency notifications to predefined contact groups, with the system automatically generating contextual messages including current GPS coordinates, nearest evacuation shelter information, and disaster type assessment. 

## Notes

This project demonstrates a complete disaster response system design, from frontend user interfaces to backend data processing and external API integration, forming a fully functional emergency preparedness platform. The system is specifically customized for Fukui Prefecture's geographical environment and disaster characteristics, including flood path obstacle avoidance, multilingual support, and localized disaster type classifications.
