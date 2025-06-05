import React, { useState } from 'react';
import axios from 'axios';

function App() {
  const [userGender, setUserGender] = useState('female');
  const [userPrompt, setUserPrompt] = useState('');
  const [brandInput, setBrandInput] = useState('');
  const [preferredBrands, setPreferredBrands] = useState([]);
  const [numOfOutfits, setNumOfOutfits] = useState(3);
  const [userId, setUserId] = useState('test-user-id');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState(null);

  // Add a brand to the list
  const addBrand = () => {
    if (brandInput.trim() !== '' && !preferredBrands.includes(brandInput.trim())) {
      setPreferredBrands([...preferredBrands, brandInput.trim()]);
      setBrandInput('');
    }
  };

  // Remove a brand from the list
  const removeBrand = (brand) => {
    setPreferredBrands(preferredBrands.filter(b => b !== brand));
  };

  // Handle form submission
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResults(null);

    try {
      const response = await axios.post('http://localhost:8000/stylist', {
        user_gender: userGender,
        user_prompt: userPrompt,
        user_preferred_brands: preferredBrands,
        num_of_outfits: parseInt(numOfOutfits),
        user_id: userId
      });

      setResults(response.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'An error occurred');
      console.error('Error:', err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <h1>Stylist API Tester</h1>
      
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="user-gender">User Gender:</label>
          <select 
            id="user-gender" 
            value={userGender} 
            onChange={(e) => setUserGender(e.target.value)}
          >
            <option value="female">Female</option>
            <option value="male">Male</option>
            <option value="non-binary">Non-binary</option>
          </select>
        </div>

        <div>
          <label htmlFor="user-prompt">User Prompt:</label>
          <textarea 
            id="user-prompt" 
            value={userPrompt} 
            onChange={(e) => setUserPrompt(e.target.value)}
            rows={4}
            placeholder="E.g., I need a casual outfit for a weekend brunch"
            required
          />
        </div>

        <div className="brands-container">
          <label htmlFor="preferred-brands">Preferred Brands:</label>
          <div className="brands-input-container">
            <input 
              id="preferred-brands" 
              value={brandInput} 
              onChange={(e) => setBrandInput(e.target.value)}
              placeholder="Enter a brand name"
            />
            <button type="button" onClick={addBrand}>Add</button>
          </div>
          
          {preferredBrands.length > 0 && (
            <div className="brand-chips">
              {preferredBrands.map((brand, index) => (
                <span key={index} className="brand-chip" onClick={() => removeBrand(brand)}>
                  {brand} ✕
                </span>
              ))}
            </div>
          )}
        </div>

        <div>
          <label htmlFor="num-outfits">Number of Outfits:</label>
          <input 
            id="num-outfits" 
            type="number" 
            min="1" 
            max="10" 
            value={numOfOutfits} 
            onChange={(e) => setNumOfOutfits(e.target.value)}
          />
        </div>

        <div>
          <label htmlFor="user-id">User ID (for testing):</label>
          <input 
            id="user-id" 
            value={userId} 
            onChange={(e) => setUserId(e.target.value)}
          />
        </div>

        <button type="submit" disabled={loading}>
          {loading ? 'Generating Outfits...' : 'Generate Outfits'}
        </button>
      </form>

      {error && (
        <div className="error">
          <h3>Error:</h3>
          <p>{error}</p>
        </div>
      )}

      {loading && (
        <div className="loading">
          <p>Generating outfits... This may take a minute or two.</p>
        </div>
      )}

      {results && (
        <div className="results">
          <h2>Results:</h2>
          {results.outfits ? (
            <div>
              {results.outfits.map((outfit, index) => (
                <div key={index} className="outfit-card">
                  <div className="outfit-header">
                    <h3>{outfit.name}</h3>
                  </div>
                  <p><strong>Description:</strong> {outfit.description}</p>
                  
                  {outfit.items && outfit.items.length > 0 && (
                    <div className="products-list">
                      <h4>Products:</h4>
                      {outfit.items.map((product, prodIndex) => (
                        <div key={prodIndex} className="product-item">
                          <p><strong>{product.type}:</strong> {product.title}</p>
                          {product.source && <p><strong>Brand:</strong> {product.source}</p>}
                          {product.images && <img height={300}  src={product.images[0]} alt={product.name} />}
                          {product.price && <p><strong>Price:</strong> ${product.price}</p>}
                          {product.link && (
                            <p><a href={product.link} target="_blank" rel="noopener noreferrer">View Product</a></p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <pre>{JSON.stringify(results, null, 2)}</pre>
          )}
        </div>
      )}
    </div>
  );
}

export default App;
