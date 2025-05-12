from flask import Flask, jsonify
from flask_restful import Api, Resource
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from datetime import datetime
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
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    return options

def save_to_firebase(collection_name, data, timestamp):
    """Save data to Firebase if available"""
    if db is not None:
        try:
            db.collection(collection_name).document('latest').set({
                'data': data,
                'last_updated': timestamp
            })
            logger.info(f"Data saved to Firebase {collection_name}")
        except Exception as e:
            logger.error(f"Error saving to Firebase {collection_name}: {str(e)}")

def scrape_pagasa_water_level():
    """Scrapes the water level data table from PAGASA website"""
    global latest_water_data, last_updated
    
    while scraping_active:
        driver = None
        try:
            logger.info("Starting water level scraping...")
            options = get_chrome_options()
            
            # Initialize browser with service
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            
            # Set page load timeout
            driver.set_page_load_timeout(30)
            
            # Navigate to the page
            driver.get("https://pasig-marikina-tullahanffws.pagasa.dost.gov.ph/water/table.do")
            
            # Wait for table to load
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.table-type1"))
            )
            time.sleep(5)  # Increased wait time
            
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            search_time_div = soup.find('div', {'class': 'search-time'})
            search_time = search_time_div.get_text(strip=True) if search_time_div else datetime.now().strftime("%Y-%m-%d %H:%M")
            
            table = soup.find('table', {'class': 'table-type1'})
            if not table:
                logger.error("Could not find water level data table")
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
            
            latest_water_data = data
            last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Save to Firebase
            save_to_firebase('water_levels', data, last_updated)
            
            logger.info(f"Water level data updated at {last_updated}")
            
        except Exception as e:
            logger.error(f"Error during water level scraping: {str(e)}")
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
        
        time.sleep(300)  # 5 minutes

def scrape_pagasa_rainfall():
    """Scrapes the rainfall data table from PAGASA website"""
    global latest_rainfall_data, last_updated
    
    while scraping_active:
        driver = None
        try:
            logger.info("Starting rainfall scraping...")
            options = get_chrome_options()
            
            # Initialize browser with service
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            
            # Set page load timeout
            driver.set_page_load_timeout(30)
            
            # Navigate to the page
            driver.get("https://pasig-marikina-tullahanffws.pagasa.dost.gov.ph/rainfall/table.do")
            
            # Wait for table to load
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "table.table-type1"))
            )
            time.sleep(5)  # Increased wait time
            
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            search_time_div = soup.find('div', {'class': 'search-time'})
            search_time = search_time_div.get_text(strip=True) if search_time_div else datetime.now().strftime("%Y-%m-%d %H:%M")
            
            table = soup.find('table', {'class': 'table-type1'})
            if not table:
                logger.error("Could not find rainfall data table")
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
            
            latest_rainfall_data = data
            last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Save to Firebase
            save_to_firebase('rainfall_data', data, last_updated)
            
            logger.info(f"Rainfall data updated at {last_updated}")
            
        except Exception as e:
            logger.error(f"Error during rainfall scraping: {str(e)}")
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass
        
        time.sleep(300)  # 5 minutes

class WaterLevelData(Resource):
    def get(self):
        if latest_water_data is None:
            return {'error': 'Water level data not available yet'}, 503
        
        return {
            'status': 'success',
            'last_updated': last_updated,
            'data': latest_water_data
        }

class RainfallData(Resource):
    def get(self):
        if latest_rainfall_data is None:
            return {'error': 'Rainfall data not available yet'}, 503
        
        return {
            'status': 'success',
            'last_updated': last_updated,
            'data': latest_rainfall_data
        }

api.add_resource(WaterLevelData, '/water-level')
api.add_resource(RainfallData, '/rainfall')

def start_scrapers():
    """Start the background scraper threads"""
    water_thread = threading.Thread(target=scrape_pagasa_water_level)
    rainfall_thread = threading.Thread(target=scrape_pagasa_rainfall)
    
    water_thread.daemon = True
    rainfall_thread.daemon = True
    
    water_thread.start()
    rainfall_thread.start()
    logger.info("Scraper threads started")

if __name__ == '__main__':
    # Start the background scrapers
    start_scrapers()
    
    # Get port from environment variable or use default
    port = int(os.environ.get('PORT', 10000))
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=port, debug=False)