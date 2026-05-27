import requests

def get_reddit_posts(subreddit, limit=10):
    url = f"https://www.reddit.com/r/{subreddit}/.json?limit={limit}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"Failed to retrieve data from Reddit. Status code: {response.status_code}")
        return []
    
    data = response.json()
    
    posts = []
    for post in data.get('data', {}).get('children', [])[:limit]:
        post_data = post.get('data', {})
        title = post_data.get('title')
        permalink = post_data.get('permalink')
        if title and permalink:
            posts.append({
                'title': title,
                'url': f"https://www.reddit.com{permalink}"
            })
    
    return posts

def get_post_content(post_url):
    if not post_url.endswith('.json'):
        post_url = post_url.rstrip('/') + '.json'
        
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    response = requests.get(post_url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to retrieve post from Reddit. Status code: {response.status_code}")
        return None
        
    data = response.json()
    if not isinstance(data, list) or len(data) < 2:
        return None
        
    post_data = data[0]['data']['children'][0]['data']
    comments_data = data[1]['data']['children']
    
    content = {
        'title': post_data.get('title'),
        'caption': post_data.get('selftext'),
        'image_url': post_data.get('url'),
        'likes': post_data.get('ups'),
        'comments': []
    }
    
    def extract_comments(comment_list):
        extracted = []
        for c in comment_list:
            if c.get('kind') == 't1':  # t1 means comment
                c_data = c.get('data', {})
                body = c_data.get('body')
                if body:
                    extracted.append(body)
                replies = c_data.get('replies')
                if isinstance(replies, dict) and replies.get('kind') == 'Listing':
                    extracted.extend(extract_comments(replies.get('data', {}).get('children', [])))
        return extracted
        
    content['comments'] = extract_comments(comments_data)
    return content

if __name__ == "__main__":
    subreddit = input("Enter the subreddit you want to fetch posts from: ")
    posts = get_reddit_posts(subreddit)
    
    print(f"Top {len(posts)} posts from r/{subreddit}:")
    for idx, post in enumerate(posts, 1):
        print(f"{idx}. {post['title']}")

    if posts:                                                                                                                                  
        first_post_url = posts[0]['url']                                                                                                       
        details = get_post_content(first_post_url)                                                                                             
        print(details['caption'])                                                                                                              
        print(details['comments']) 