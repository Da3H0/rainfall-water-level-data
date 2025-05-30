from flask import Flask, jsonify, render_template_string, request
from flask_restful import Api, Resource
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import threading
import time
import os
import firebase_admin
from firebase_admin import credentials, firestore
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
api = Api(app)

# Initialize Firebase
try:
    # Try to get Firebase credentials from environment variable
    firebase_credentials = os.environ.get('FIREBASE_CREDENTIALS')
    if firebase_credentials:
        cred_dict = json.loads(firebase_credentials)
        cred = credentials.Certificate(cred_dict)
    else:
        # Fallback to local credentials file
        cred = credentials.Certificate("floodpath-1c7ef-firebase-adminsdk-fbsvc-957288a212.json")
    
    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ.get('FIREBASE_DATABASE_URL', 'https://floodpath-1c7ef.firebaseio.com')
    })
    db = firestore.client()
    logger.info("Firebase initialized successfully")
except Exception as e:
    logger.error(f"Warning: Firebase initialization failed: {str(e)}")
    db = None

# Global variables to store the latest data
latest_water_data = None
latest_rainfall_data = None
last_updated = None
scraping_active = True
last_water_hash = None  # Add this to track changes
last_rainfall_hash = None  # Add this to track changes
water_thread = None  # Add global thread variables
rainfall_thread = None

# Add this HTML template at the top of the file after the imports
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>FloodPath Data</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .section { margin-bottom: 30px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        .timestamp { color: #666; font-size: 0.9em; }
        .error { color: red; }
        .date-header { 
            background-color: #e9ecef; 
            padding: 10px; 
            margin-top: 20px; 
            border-radius: 5px;
        }
        .date-selector {
            margin: 20px 0;
            padding: 10px;
            background-color: #f8f9fa;
            border-radius: 5px;
        }
        .date-selector select {
            padding: 5px;
            margin-right: 10px;
        }
    </style>
    <script>
        function updateData() {
            const waterDate = document.getElementById('waterDate').value;
            const rainfallDate = document.getElementById('rainfallDate').value;
            
            // Fetch water level data
            fetch(`/water-level?date=${waterDate}`)
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        updateWaterTable(data.data, data.last_updated);
                    }
                });
            
            // Fetch rainfall data
            fetch(`/rainfall?date=${rainfallDate}`)
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        updateRainfallTable(data.data, data.last_updated);
                    }
                });
        }

        function updateWaterTable(data, timestamp) {
            const tbody = document.getElementById('waterTableBody');
            tbody.innerHTML = '';
            
            data.forEach(station => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${station.station}</td>
                    <td>${station.current_wl}</td>
                    <td>${station.wl_30min}</td>
                    <td>${station.wl_1hr}</td>
                    <td>${station.alert_level}</td>
                    <td>${station.alarm_level}</td>
                    <td>${station.critical_level}</td>
                `;
                tbody.appendChild(row);
            });
            
            document.getElementById('waterTimestamp').textContent = `Last updated: ${timestamp}`;
        }

        function updateRainfallTable(data, timestamp) {
            const tbody = document.getElementById('rainfallTableBody');
            tbody.innerHTML = '';
            
            data.forEach(station => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${station.station}</td>
                    <td>${station.current_rf}</td>
                    <td>${station.rf_30min}</td>
                    <td>${station.rf_1hr}</td>
                    <td>${station.rf_3hr}</td>
                    <td>${station.rf_6hr}</td>
                    <td>${station.rf_12hr}</td>
                    <td>${station.rf_24hr}</td>
                `;
                tbody.appendChild(row);
            });
            
            document.getElementById('rainfallTimestamp').textContent = `Last updated: ${timestamp}`;
        }

        // Update data every 5 minutes
        setInterval(updateData, 300000);
        // Initial load
        document.addEventListener('DOMContentLoaded', updateData);
    </script>
</head>
<body>
    <div class="container">
        <h1>FloodPath Data</h1>
        
        <div class="section">
            <h2>Water Level Data</h2>
            <div class="date-selector">
                <label for="waterDate">Select Date:</label>
                <select id="waterDate" onchange="updateData()">
                    {% for date in available_dates %}
                    <option value="{{ date }}">{{ date }}</option>
                    {% endfor %}
                </select>
            </div>
            <p id="waterTimestamp" class="timestamp">Last updated: {{ water_data.last_updated if water_data else 'Not available' }}</p>
            <table>
                <thead>
                    <tr>
                        <th>Station</th>
                        <th>Current WL</th>
                        <th>30min WL</th>
                        <th>1hr WL</th>
                        <th>Alert Level</th>
                        <th>Alarm Level</th>
                        <th>Critical Level</th>
                    </tr>
                </thead>
                <tbody id="waterTableBody">
                    {% if water_data %}
                        {% for station in water_data.data %}
                        <tr>
                            <td>{{ station.station }}</td>
                            <td>{{ station.current_wl }}</td>
                            <td>{{ station.wl_30min }}</td>
                            <td>{{ station.wl_1hr }}</td>
                            <td>{{ station.alert_level }}</td>
                            <td>{{ station.alarm_level }}</td>
                            <td>{{ station.critical_level }}</td>
                        </tr>
                        {% endfor %}
                    {% endif %}
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2>Rainfall Data</h2>
            <div class="date-selector">
                <label for="rainfallDate">Select Date:</label>
                <select id="rainfallDate" onchange="updateData()">
                    {% for date in available_dates %}
                    <option value="{{ date }}">{{ date }}</option>
                    {% endfor %}
                </select>
            </div>
            <p id="rainfallTimestamp" class="timestamp">Last updated: {{ rainfall_data.last_updated if rainfall_data else 'Not available' }}</p>
            <table>
                <thead>
                    <tr>
                        <th>Station</th>
                        <th>Current RF</th>
                        <th>30min RF</th>
                        <th>1hr RF</th>
                        <th>3hr RF</th>
                        <th>6hr RF</th>
                        <th>12hr RF</th>
                        <th>24hr RF</th>
                    </tr>
                </thead>
                <tbody id="rainfallTableBody">
                    {% if rainfall_data %}
                        {% for station in rainfall_data.data %}
                        <tr>
                            <td>{{ station.station }}</td>
                            <td>{{ station.current_rf }}</td>
                            <td>{{ station.rf_30min }}</td>
                            <td>{{ station.rf_1hr }}</td>
                            <td>{{ station.rf_3hr }}</td>
                            <td>{{ station.rf_6hr }}</td>
                            <td>{{ station.rf_12hr }}</td>
                            <td>{{ station.rf_24hr }}</td>
                        </tr>
                        {% endfor %}
                    {% endif %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""

def get_chrome_options():
    """Configure Chrome options for cloud environment"""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-infobars')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--start-maximized')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-features=VizDisplayCompositor')
    options.add_argument('--disable-features=IsolateOrigins,site-per-process')
    options.add_argument('--disable-site-isolation-trials')
    options.add_argument('--disable-web-security')
    options.add_argument('--allow-running-insecure-content')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--disable-gpu-sandbox')
    options.add_argument('--disable-setuid-sandbox')
    options.add_argument('--no-first-run')
    options.add_argument('--no-zygote')
    options.add_argument('--single-process')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-accelerated-2d-canvas')
    options.add_argument('--disable-gl-drawing-for-tests')
    options.add_argument('--remote-debugging-port=9222')
    options.add_argument('--remote-debugging-address=0.0.0.0')
    options.add_argument('--disable-background-networking')
    options.add_argument('--disable-background-timer-throttling')
    options.add_argument('--disable-backgrounding-occluded-windows')
    options.add_argument('--disable-breakpad')
    options.add_argument('--disable-component-extensions-with-background-pages')
    options.add_argument('--disable-default-apps')
    options.add_argument('--disable-features=TranslateUI')
    options.add_argument('--disable-ipc-flooding-protection')
    options.add_argument('--disable-renderer-backgrounding')
    options.add_argument('--enable-features=NetworkService,NetworkServiceInProcess')
    options.add_argument('--force-color-profile=srgb')
    options.add_argument('--metrics-recording-only')
    options.add_argument('--mute-audio')
    options.add_argument('--no-default-browser-check')
    options.add_argument('--no-pings')
    options.add_argument('--password-store=basic')
    options.add_argument('--use-mock-keychain')
    options.add_argument('--disable-hang-monitor')
    options.add_argument('--disable-prompt-on-repost')
    options.add_argument('--disable-sync')
    options.add_argument('--force-device-scale-factor=1')
    options.add_argument('--hide-scrollbars')
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-popup-blocking')
    options.add_argument('--disable-save-password-bubble')
    options.add_argument('--disable-translate')
    options.add_argument('--disable-web-security')
    options.add_argument('--disable-features=IsolateOrigins,site-per-process')
    options.add_argument('--disable-site-isolation-trials')
    options.add_argument('--disable-web-security')
    options.add_argument('--allow-running-insecure-content')
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Add experimental options
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    return options

def calculate_data_hash(data):
    """Calculate a hash of the data to detect changes"""
    import hashlib
    return hashlib.md5(str(data).encode()).hexdigest()

def save_to_firebase(collection_name, data, timestamp):
    """Save data to Firebase if available"""
    if db is not None:
        try:
            # Parse the timestamp to get the date
            try:
                date_obj = datetime.strptime(timestamp, "%Y-%m-%d %H:%M")
                date_str = date_obj.strftime("%Y-%m-%d")
            except:
                date_str = datetime.now().strftime("%Y-%m-%d")

            # Create a copy of the data to avoid modifying the original
            data_copy = []
            for item in data:
                item_copy = item.copy()
                # Remove the firebase_timestamp from individual items
                if 'firebase_timestamp' in item_copy:
                    del item_copy['firebase_timestamp']
                data_copy.append(item_copy)
            
            # Save to date-based collection
            date_collection = f"{collection_name}_{date_str}"
            db.collection(date_collection).document('latest').set({
                'data': data_copy,
                'last_updated': timestamp,
                'firebase_timestamp': firestore.SERVER_TIMESTAMP
            })
            
            # Also save to the main collection for latest data
            db.collection(collection_name).document('latest').set({
                'data': data_copy,
                'last_updated': timestamp,
                'firebase_timestamp': firestore.SERVER_TIMESTAMP
            })
            
            logger.info(f"Data saved to Firebase {date_collection} at {timestamp}")
        except Exception as e:
            logger.error(f"Error saving to Firebase {collection_name}: {str(e)}")

def initialize_webdriver():
    """Initialize and return a configured webdriver instance"""
    try:
        logger.info("Initializing webdriver...")
        options = get_chrome_options()
        
        # Log Chrome binary path in production
        if os.environ.get('RENDER'):
            logger.info("Running in production environment (Render)")
            chrome_path = os.environ.get('CHROME_BIN', '/usr/bin/google-chrome-stable')
            logger.info(f"Chrome binary path: {chrome_path}")
            
            # Verify Chrome binary exists
            if not os.path.exists(chrome_path):
                logger.error(f"Chrome binary not found at {chrome_path}")
                # Try to find Chrome in common locations
                common_paths = [
                    '/usr/bin/google-chrome-stable',
                    '/usr/bin/google-chrome',
                    '/usr/bin/chrome',
                    '/usr/bin/chromium',
                    '/usr/bin/chromium-browser'
                ]
                for path in common_paths:
                    if os.path.exists(path):
                        logger.info(f"Found Chrome at {path}")
                        chrome_path = path
                        break
                else:
                    logger.error("Chrome not found in common locations")
                    return None
            
            options.binary_location = chrome_path
            
            # Add display configuration for headless mode
            os.environ['DISPLAY'] = ':99'
            
            # Add additional options for Render environment
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-software-rasterizer')
            options.add_argument('--disable-extensions')
            options.add_argument('--single-process')
            options.add_argument('--no-zygote')
            options.add_argument('--disable-dev-shm-usage')
        
        # Try to use Chrome from PATH first
        try:
            logger.info("Attempting to use Chrome from PATH...")
            service = Service()
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(30)
            logger.info("Successfully initialized Chrome from PATH")
            return driver
        except Exception as e:
            logger.warning(f"Failed to use Chrome from PATH: {str(e)}")
        
        # Fallback to ChromeDriverManager
        try:
            logger.info("Attempting to use ChromeDriverManager...")
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(30)
            logger.info("Successfully initialized Chrome with ChromeDriverManager")
            return driver
        except Exception as e:
            logger.error(f"Failed to initialize Chrome with ChromeDriverManager: {str(e)}")
            raise
        
    except Exception as e:
        logger.error(f"Error initializing webdriver: {str(e)}")
        return None

def scrape_pagasa_water_level():
    """Scrapes the water level data table from PAGASA website"""
    global latest_water_data, last_updated, last_water_hash
    
    consecutive_failures = 0
    max_failures = 5  # Maximum number of consecutive failures before longer delay
    
    while scraping_active:
        driver = None
        try:
            logger.info("Starting water level scraping...")
            driver = initialize_webdriver()
            if not driver:
                logger.error("Failed to initialize webdriver for water level scraping")
                consecutive_failures += 1
                time.sleep(60 * min(consecutive_failures, max_failures))
                continue
            
            # Navigate to the page
            logger.info("Navigating to water level page...")
            driver.get("https://pasig-marikina-tullahanffws.pagasa.dost.gov.ph/water/table.do")
            
            # Wait for table to load with increased timeout
            logger.info("Waiting for water level table to load...")
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.table-type1"))
            )
            time.sleep(10)  # Increased wait time
            
            # Check if page is loaded
            if "table.do" not in driver.current_url:
                logger.error("Failed to load water level page")
                consecutive_failures += 1
                time.sleep(60 * min(consecutive_failures, max_failures))
                continue
            
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            search_time_div = soup.find('div', {'class': 'search-time'})
            search_time = search_time_div.get_text(strip=True) if search_time_div else datetime.now().strftime("%Y-%m-%d %H:%M")
            
            table = soup.find('table', {'class': 'table-type1'})
            if not table:
                logger.error("Could not find water level data table")
                consecutive_failures += 1
                time.sleep(60 * min(consecutive_failures, max_failures))
                continue
            
            data = []
            for row in table.find('tbody').find_all('tr'):
                cols = row.find_all(['th', 'td'])
                if len(cols) >= 7:
                    station = cols[0].get_text(strip=True)
                    current_wl = cols[1].get_text(strip=True)
                    wl_30min = cols[2].get_text(strip=True)
                    wl_1hr = cols[3].get_text(strip=True)
                    alert = cols[4].get_text(strip=True)
                    alarm = cols[5].get_text(strip=True)
                    critical = cols[6].get_text(strip=True)
                    
                    data.append({
                        'station': station,
                        'current_wl': current_wl,
                        'wl_30min': wl_30min,
                        'wl_1hr': wl_1hr,
                        'alert_level': alert,
                        'alarm_level': alarm,
                        'critical_level': critical,
                        'timestamp': search_time
                    })
            
            if not data:
                logger.error("No water level data was scraped")
                consecutive_failures += 1
                time.sleep(60 * min(consecutive_failures, max_failures))
                continue
            
            # Reset consecutive failures on success
            consecutive_failures = 0
            
            # Calculate hash of new data
            new_hash = calculate_data_hash(data)
            
            # Only update if data has changed
            if new_hash != last_water_hash:
                latest_water_data = data
                last_updated = search_time
                last_water_hash = new_hash
                
                # Save to Firebase
                save_to_firebase('water_levels', data, search_time)
                logger.info(f"Water level data updated at {search_time}")
            else:
                logger.info("No changes in water level data")
            
        except Exception as e:
            logger.error(f"Error during water level scraping: {str(e)}")
            consecutive_failures += 1
            time.sleep(60 * min(consecutive_failures, max_failures))
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception as e:
                    logger.error(f"Error quitting webdriver: {str(e)}")
        
        # Calculate next scrape time to maintain 5-minute intervals
        next_scrape = datetime.now() + timedelta(minutes=5)
        time.sleep(max(0, (next_scrape - datetime.now()).total_seconds()))

def scrape_pagasa_rainfall():
    """Scrapes the rainfall data table from PAGASA website"""
    global latest_rainfall_data, last_updated, last_rainfall_hash
    
    consecutive_failures = 0
    max_failures = 5  # Maximum number of consecutive failures before longer delay
    
    while scraping_active:
        driver = None
        try:
            logger.info("Starting rainfall scraping...")
            driver = initialize_webdriver()
            if not driver:
                logger.error("Failed to initialize webdriver for rainfall scraping")
                consecutive_failures += 1
                time.sleep(60 * min(consecutive_failures, max_failures))
                continue
            
            # Navigate to the page
            driver.get("https://pasig-marikina-tullahanffws.pagasa.dost.gov.ph/rainfall/table.do")
            
            # Wait for table to load with increased timeout
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.table-type1"))
            )
            time.sleep(10)  # Increased wait time
            
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            search_time_div = soup.find('div', {'class': 'search-time'})
            search_time = search_time_div.get_text(strip=True) if search_time_div else datetime.now().strftime("%Y-%m-%d %H:%M")
            
            table = soup.find('table', {'class': 'table-type1'})
            if not table:
                logger.error("Could not find rainfall data table")
                consecutive_failures += 1
                time.sleep(60 * min(consecutive_failures, max_failures))
                continue
            
            data = []
            for row in table.find('tbody').find_all('tr'):
                cols = row.find_all(['th', 'td'])
                if len(cols) >= 8:
                    station = cols[0].get_text(strip=True)
                    current_rf = cols[1].get_text(strip=True)
                    rf_30min = cols[2].get_text(strip=True)
                    rf_1hr = cols[3].get_text(strip=True)
                    rf_3hr = cols[4].get_text(strip=True)
                    rf_6hr = cols[5].get_text(strip=True)
                    rf_12hr = cols[6].get_text(strip=True)
                    rf_24hr = cols[7].get_text(strip=True)
                    
                    data.append({
                        'station': station,
                        'current_rf': current_rf,
                        'rf_30min': rf_30min,
                        'rf_1hr': rf_1hr,
                        'rf_3hr': rf_3hr,
                        'rf_6hr': rf_6hr,
                        'rf_12hr': rf_12hr,
                        'rf_24hr': rf_24hr,
                        'timestamp': search_time
                    })
            
            if not data:
                logger.error("No rainfall data was scraped")
                consecutive_failures += 1
                time.sleep(60 * min(consecutive_failures, max_failures))
                continue
            
            # Reset consecutive failures on success
            consecutive_failures = 0
            
            # Calculate hash of new data
            new_hash = calculate_data_hash(data)
            
            # Only update if data has changed
            if new_hash != last_rainfall_hash:
                latest_rainfall_data = data
                last_updated = search_time
                last_rainfall_hash = new_hash
                
                # Save to Firebase
                save_to_firebase('rainfall_data', data, search_time)
                logger.info(f"Rainfall data updated at {search_time}")
            else:
                logger.info("No changes in rainfall data")
            
        except Exception as e:
            logger.error(f"Error during rainfall scraping: {str(e)}")
            consecutive_failures += 1
            time.sleep(60 * min(consecutive_failures, max_failures))
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
        
        # Calculate next scrape time to maintain 5-minute intervals
        next_scrape = datetime.now() + timedelta(minutes=5)
        time.sleep(max(0, (next_scrape - datetime.now()).total_seconds()))

class WaterLevelData(Resource):
    def get(self):
        date = request.args.get('date')
        if date:
            try:
                # Try to get data for specific date
                doc = db.collection(f'water_levels_{date}').document('latest').get()
                if doc.exists:
                    return {
                        'status': 'success',
                        'last_updated': doc.get('last_updated'),
                        'data': doc.get('data')
                    }
            except Exception as e:
                logger.error(f"Error fetching water level data for date {date}: {str(e)}")
        
        # Fallback to latest data
        if latest_water_data is None:
            return {'error': 'Water level data not available yet'}, 503
        
        return {
            'status': 'success',
            'last_updated': last_updated,
            'data': latest_water_data
        }

class RainfallData(Resource):
    def get(self):
        date = request.args.get('date')
        if date:
            try:
                # Try to get data for specific date
                doc = db.collection(f'rainfall_data_{date}').document('latest').get()
                if doc.exists:
                    return {
                        'status': 'success',
                        'last_updated': doc.get('last_updated'),
                        'data': doc.get('data')
                    }
            except Exception as e:
                logger.error(f"Error fetching rainfall data for date {date}: {str(e)}")
        
        # Fallback to latest data
        if latest_rainfall_data is None:
            return {'error': 'Rainfall data not available yet'}, 503
        
        return {
            'status': 'success',
            'last_updated': last_updated,
            'data': latest_rainfall_data
        }

@app.route('/')
def index():
    # Get available dates from Firebase
    available_dates = []
    try:
        if db:
            # Get all collections
            collections = db.collections()
            for collection in collections:
                if collection.id.startswith('water_levels_') or collection.id.startswith('rainfall_data_'):
                    date = collection.id.split('_')[-1]
                    if date not in available_dates:
                        available_dates.append(date)
    except Exception as e:
        logger.error(f"Error fetching available dates: {str(e)}")
    
    # Sort dates in descending order
    available_dates.sort(reverse=True)
    
    return render_template_string(HTML_TEMPLATE, 
                                water_data={'data': latest_water_data, 'last_updated': last_updated} if latest_water_data else None,
                                rainfall_data={'data': latest_rainfall_data, 'last_updated': last_updated} if latest_rainfall_data else None,
                                available_dates=available_dates)

api.add_resource(WaterLevelData, '/water-level')
api.add_resource(RainfallData, '/rainfall')

def start_scrapers():
    """Start the background scraper threads"""
    global water_thread, rainfall_thread, scraping_active
    
    try:
        # Test webdriver initialization before starting threads
        logger.info("Testing webdriver initialization...")
        test_driver = initialize_webdriver()
        if test_driver:
            test_driver.quit()
            logger.info("Webdriver test successful")
        else:
            logger.error("Webdriver test failed")
            scraping_active = False
            return
        
        water_thread = threading.Thread(target=scrape_pagasa_water_level)
        rainfall_thread = threading.Thread(target=scrape_pagasa_rainfall)
        
        water_thread.daemon = True
        rainfall_thread.daemon = True
        
        water_thread.start()
        rainfall_thread.start()
        logger.info("Scraper threads started successfully")
        
        # Add error handling for thread monitoring
        def monitor_threads():
            global water_thread, rainfall_thread, scraping_active
            while scraping_active:
                try:
                    if not water_thread.is_alive():
                        logger.error("Water level scraper thread died, restarting...")
                        water_thread = threading.Thread(target=scrape_pagasa_water_level)
                        water_thread.daemon = True
                        water_thread.start()
                    
                    if not rainfall_thread.is_alive():
                        logger.error("Rainfall scraper thread died, restarting...")
                        rainfall_thread = threading.Thread(target=scrape_pagasa_rainfall)
                        rainfall_thread.daemon = True
                        rainfall_thread.start()
                    
                    time.sleep(60)  # Check every minute
                except Exception as e:
                    logger.error(f"Error in thread monitoring: {str(e)}")
                    time.sleep(60)  # Wait before retrying
        
        monitor_thread = threading.Thread(target=monitor_threads)
        monitor_thread.daemon = True
        monitor_thread.start()
        
    except Exception as e:
        logger.error(f"Error starting scraper threads: {str(e)}")
        scraping_active = False

# Initialize scraping when the module is imported
try:
    logger.info("Starting scraper initialization...")
    start_scrapers()
except Exception as e:
    logger.error(f"Failed to start scrapers: {str(e)}")
    scraping_active = False

# Add health check endpoint
@app.route('/health')
def health_check():
    """Health check endpoint for uptime monitoring"""
    try:
        # Check if scraping is active
        if not scraping_active:
            return jsonify({
                'status': 'error',
                'message': 'Scraping is not active',
                'water_thread_alive': water_thread.is_alive() if water_thread else False,
                'rainfall_thread_alive': rainfall_thread.is_alive() if rainfall_thread else False
            }), 503
        
        # Check if we have recent data
        current_time = datetime.now()
        if last_updated:
            last_update_time = datetime.strptime(last_updated, "%Y-%m-%d %H:%M")
            time_diff = (current_time - last_update_time).total_seconds()
            
            # If no updates in last 10 minutes, consider it unhealthy
            if time_diff > 600:  # 10 minutes
                return jsonify({
                    'status': 'warning',
                    'message': f'No data updates in {int(time_diff/60)} minutes',
                    'last_update': last_updated,
                    'water_thread_alive': water_thread.is_alive() if water_thread else False,
                    'rainfall_thread_alive': rainfall_thread.is_alive() if rainfall_thread else False
                }), 200
        
        return jsonify({
            'status': 'healthy',
            'last_update': last_updated,
            'water_data_available': latest_water_data is not None,
            'rainfall_data_available': latest_rainfall_data is not None,
            'water_thread_alive': water_thread.is_alive() if water_thread else False,
            'rainfall_thread_alive': rainfall_thread.is_alive() if rainfall_thread else False
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    # Get port from environment variable or use default
    port = int(os.environ.get('PORT', 10000))
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=port, debug=False)