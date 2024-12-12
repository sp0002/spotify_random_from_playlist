# spotify_random_from_playlist
Create/replace a playlist with n random songs from another playlist.

## Unresolved
When access token expires (1 hour), the token refresh logic is not fully working.

## Configuring Spotify's side
Go to https://developer.spotify.com/ and log in. You can use the same account you use for listening to songs.

Go to https://developer.spotify.com/dashboard and click on "Create app".

Use any app name/description as you wish.

### Redirect URIs
For Redirect URIs, add https://localhost:5005/callback, or http://localhost:5005/callback if you are not using SSL/TLS.

Check Web API under the section: Which API/SDKs are you planning to use?

Save the app details.

### Getting essential app details
Go to https://developer.spotify.com/dashboard and click the app you just created.
Click on settings on the top right.
Click on view client secret.

Copy Client ID to CLIENT_ID in .env and Client secret to CLIENT_SECRET in .env
That's all you need on Spotify developer dashboard.


## Pip installing
You might want to use a virtual environment.

pip install -r requirements.txt


## Running
python main.py

python3 main.py

## Entering the site
Go to any browser and go to https://localhost:5005/callback.

## Changing the number of songs generated
Change NUM_SONGS in .env

## Assumptions
You have Spotify premium.

## Expanding
This was made for single/small amounts of users. If you are supporting more users, consider using more database operations (like Redis) to cache songs and playlists to avoid running into rate limits and other problems. 