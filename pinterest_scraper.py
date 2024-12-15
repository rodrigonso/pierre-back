from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import json
import os

class PinterestScraper:
    def __init__(self):
        # Initialize Chrome options
        self.chrome_options = webdriver.ChromeOptions()
        # Add additional Chrome options for stability
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument('--disable-gpu')
        self.chrome_options.add_argument('--disable-extensions')
        self.chrome_options.add_argument('--disable-software-rasterizer')
        # Uncomment the line below to run Chrome in headless mode
        self.chrome_options.add_argument('--headless')
        
        try:
            # Setup Chrome service with webdriver_manager
            # service = Service(ChromeDriverManager().install())
            chrome_install = ChromeDriverManager().install()

            folder = os.path.dirname(chrome_install)
            chromedriver_path = os.path.join(folder, "chromedriver.exe")

            service = Service(chromedriver_path)
            self.driver = webdriver.Chrome(service=service, options=self.chrome_options)
        except Exception as e:
            raise Exception(f"Failed to initialize Chrome driver: {str(e)}")
        
        self.base_url = "https://www.pinterest.com"
        
    def login(self, email, password):
        """Login to Pinterest account"""
        try:
            self.driver.get(self.base_url)
            time.sleep(2)
            
            # Click login button
            login_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-test-id="simple-login-button"]'))
            )
            login_button.click()
            
            # Enter email
            email_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "email"))
            )
            email_input.send_keys(email)
            
            # Enter password
            password_input = self.driver.find_element(By.ID, "password")
            password_input.send_keys(password)
            
            # Submit login form
            password_input.send_keys(Keys.RETURN)
            time.sleep(5)
            
            return True
            
        except Exception as e:
            print(f"Login failed: {str(e)}")
            return False
    
    def search_pins(self, query, num_pins=50):
        """Search Pinterest for pins based on query"""
        try:
            # Navigate to search URL
            search_url = f"{self.base_url}/search/pins/?q={query.replace(' ', '+')}"
            self.driver.get(search_url)
            time.sleep(3)
            
            pins_data = []
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            
            while len(pins_data) < num_pins:
                # Scroll down
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                # Get all pin elements
                pins = self.driver.find_elements(By.CSS_SELECTOR, '[data-test-id="pin"]')
                
                for pin in pins:
                    if len(pins_data) >= num_pins:
                        break
                        
                    try:
                        # Get pin link
                        pin_link = pin.find_element(By.CSS_SELECTOR, 'a').get_attribute('href')
                        
                        # Visit pin detail page to get tags
                        self.driver.execute_script("window.open('');")
                        self.driver.switch_to.window(self.driver.window_handles[-1])
                        self.driver.get(pin_link)
                        time.sleep(1)
                        
                        # Extract tags using the correct selector
                        tags = []
                        try:
                            tag_elements = WebDriverWait(self.driver, 5).until(
                                EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[data-test-id="vase-tag"]'))
                            )
                            tags = [tag.text.strip() for tag in tag_elements]

                            title_element = WebDriverWait(self.driver, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-test-id="pinTitle"]'))
                            )
                            title = title_element.text.strip()
                        except:
                            pass
                        
                        # Close pin detail page and switch back to search results
                        self.driver.close()
                        self.driver.switch_to.window(self.driver.window_handles[0])
                        
                        pin_data = {
                            'title': title,
                            'link': pin_link,
                            'image': pin.find_element(By.CSS_SELECTOR, 'img').get_attribute('src'),
                            'tags': tags
                        }
                        
                        if pin_data not in pins_data:
                            pins_data.append(pin_data)
                            print(f"Scraped {len(pins_data)} pins", end='\r')
                            
                    except Exception as e:
                        if len(self.driver.window_handles) > 1:
                            self.driver.close()
                            self.driver.switch_to.window(self.driver.window_handles[0])
                        continue
                
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
                
            return pins_data
            
        except Exception as e:
            print(f"Search failed: {str(e)}")
            return []
    
    def save_results(self, pins_data, filename):
        """Save scraped data to JSON file"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(pins_data, f, indent=4)
            print(f"Results saved to {filename}")
        except Exception as e:
            print(f"Failed to save results: {str(e)}")
    
    def close(self):
        """Close the browser"""
        self.driver.quit()
    
    def get_trending_pins(self, num_pins=50):
        """Scrape trending style inspiration pins"""
        try:
            # Navigate to trending page
            trending_url = "https://www.pinterest.com/today/article/trending-style-inspo/123644/"
            self.driver.get(trending_url)
            time.sleep(3)
            
            pins_data = []
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            
            while len(pins_data) < num_pins:
                # Scroll down
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                
                # Get all pin elements
                pins = self.driver.find_elements(By.CSS_SELECTOR, '[data-test-id="pin"]')
                
                for pin in pins:
                    if len(pins_data) >= num_pins:
                        break
                    
                    try:
                        # Get pin link
                        pin_link = pin.find_element(By.CSS_SELECTOR, 'a').get_attribute('href')
                        
                        # Visit pin detail page to get tags
                        self.driver.execute_script("window.open('');")
                        self.driver.switch_to.window(self.driver.window_handles[-1])
                        self.driver.get(pin_link)
                        time.sleep(1)
                        
                        # Extract tags using the correct selector
                        tags = []
                        try:
                            tag_elements = WebDriverWait(self.driver, 5).until(
                                EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[data-test-id="vase-tag"]'))
                            )
                            tags = [tag.text.strip() for tag in tag_elements]

                            title = WebDriverWait(self.driver, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, '[data-test-id="pinTitle"]'))
                            )
                            title = title.text.strip()
                        except:
                            pass
                        
                        # Close pin detail page and switch back to search results
                        self.driver.close()
                        self.driver.switch_to.window(self.driver.window_handles[0])
                        
                        pin_data = {
                            'title': title,
                            'link': pin_link,
                            'image': pin.find_element(By.CSS_SELECTOR, 'img').get_attribute('src'),
                            'tags': tags,
                        }
                        
                        if pin_data not in pins_data:
                            pins_data.append(pin_data)
                            print(f"Scraped {len(pins_data)} trending pins", end='\r')
                        
                    except Exception as e:
                        if len(self.driver.window_handles) > 1:
                            self.driver.close()
                            self.driver.switch_to.window(self.driver.window_handles[0])
                        continue
                
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
                
            return pins_data
            
        except Exception as e:
            print(f"Failed to get trending pins: {str(e)}")
            return []