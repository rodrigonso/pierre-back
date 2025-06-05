# Stylist API Tester

A simple React application for testing the stylist endpoint of the Pierre backend API.

## Setup

1. Make sure the Pierre backend server is running on http://localhost:8000
2. Install dependencies:
   ```
   npm install
   ```
3. Start the development server:
   ```
   npm start
   ```

## Usage

1. Fill out the form with the following information:
   - User Gender: Select the gender for the styling request
   - User Prompt: Enter a styling request (e.g., "I need a casual outfit for a weekend brunch")
   - Preferred Brands: Add any preferred brands (optional)
   - Number of Outfits: Choose how many outfit suggestions you want
   - User ID: For testing purposes, defaults to "test-user-id"

2. Click "Generate Outfits" to submit the request to the stylist endpoint.

3. The results will be displayed below the form. Each outfit will include:
   - Name
   - Description
   - Products list (if available)

## Troubleshooting

- If you receive a "Network Error", ensure that the Pierre backend API is running on http://localhost:8000
- If CORS errors occur, make sure the backend has proper CORS configuration enabled
- For other errors, check the browser console for more details
