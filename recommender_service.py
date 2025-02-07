import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class ProductRecommender:
    def __init__(self, products_df, interactions_df):
        self.products = products_df
        self.interactions = interactions_df
        self.tfidf_matrix = None
        self.similarity_matrix = None

    def prepare_content_features(self):
        # Combine text features for content-based filtering
        self.products['features'] = self.products['type'] + ' ' + \
                                    self.products['description']
        
        # Create TF-IDF matrix
        tfidf = TfidfVectorizer(stop_words='english')
        self.tfidf_matrix = tfidf.fit_transform(self.products['features'])
        
        # Calculate product similarity
        self.similarity_matrix = cosine_similarity(self.tfidf_matrix)

    def content_based_recommendations(self, product_id, top_n=5):
        # Find similar products based on content
        idx = self.products[self.products['id'] == product_id].index[0]
        similarity_scores = list(enumerate(self.similarity_matrix[idx]))
        
        # Sort and get top recommendations
        sorted_scores = sorted(similarity_scores, key=lambda x: x[1], reverse=True)[1:top_n+1]
        recommended_indices = [i[0] for i in sorted_scores]
        
        return self.products.iloc[recommended_indices]

    def collaborative_recommendations(self, user_id, top_n=5):
        # Simple collaborative filtering using user-product interactions
        user_interactions = self.interactions[self.interactions['user_id'] == user_id]
        
        # Get products not yet interacted with
        interacted_products = user_interactions['product_id'].tolist()
        candidate_products = self.products[~self.products['id'].isin(interacted_products)]
        
        # Calculate popularity/interaction scores
        product_scores = (
            self.interactions[~self.interactions['product_id'].isin(interacted_products)]
            .groupby('product_id')['interaction_type']
            .count()
            .sort_values(ascending=False)
            .head(top_n)
        )
        
        return self.products[self.products['id'].isin(product_scores.index)]

    def hybrid_recommendations(self, user_id, product_id, top_n=5):
        # Combine content-based and collaborative recommendations
        content_recs = self.content_based_recommendations(product_id, top_n=top_n//2)
        collab_recs = self.collaborative_recommendations(user_id, top_n=top_n//2)
        
        # Merge and deduplicate recommendations
        combined_recs = pd.concat([content_recs, collab_recs]).drop_duplicates()
        return combined_recs.head(top_n)



# Sample data preparation
products_data = pd.DataFrame({
    'id': [1, 2, 3, 4, 5],
    'type': ['sweater', 'pants', 'sweater', 'coat', 'accessory'],
    'description': [
        'Be warm & cozy with the Jessa Chunky Sweater in a blend of neutral tones. Made with chunky knit yarn, this sweater hits at the waist for a flattering and cozy fit.',
        'The Shea. This full length high-rise style is designed with a relaxed straight leg. Crafted in Lightweight Rigid non-stretch denim that provides structure, but breaks in over time for a soft and comfortable feel. In Quincy, a light indigo wash with a clean hem.',
        'New and improved this season, the cuffs and bottom of the sweater are gathered slightly, to make a closer fit. With a relaxed style, and a chunky ribbed neckline and cuffs, our loose-knit sweater made from 100 organic cotton is a warm hug in a sweater',
        'Our new double-breasted coat in a wool-blend fabric and classic fit, featuring a long-length silhouette, classic lapel collar, interior lining, button-front closure and front pockets.',
        'A more compact Cassie, our 19 is smaller than the original and made for days or nights on the go. The polished pebble leather design is finished with a Signature turnlock closure and three interchangeable straps for versatile styling. Detach the crossbody strap and carry by hand with the leather and chain top handles together or separately.'
    ],
    'price': [599.99, 49.99, 14.99, 199.99, 29.99]
})

interactions_data = pd.DataFrame({
    'user_id': [101, 101, 102],
    'product_id': [1, 4, 2],
    'interaction_type': ['like', 'dislike', 'like']
})

# Initialize recommender
recommender = ProductRecommender(products_data, interactions_data)
recommender.prepare_content_features()

# Get content-based recommendations for a specific product
content_recs = recommender.content_based_recommendations(product_id=1)
print("Content-Based Recommendations:")
print(content_recs)

# Get collaborative recommendations for a user
collab_recs = recommender.collaborative_recommendations(user_id=101)
print("\nCollaborative Recommendations:")
print(collab_recs)

# Get hybrid recommendations
hybrid_recs = recommender.hybrid_recommendations(user_id=101, product_id=1)
print("\nHybrid Recommendations:")
print(hybrid_recs)