import random
import sqlite3
import secrets
from pathlib import Path
from collections import deque
from urllib.parse import urlencode

import requests
from dotenv import dotenv_values
from flask import Flask, render_template, request, redirect, url_for, make_response
from flask_login import LoginManager, current_user, login_user, logout_user, UserMixin

path = Path(__file__).parent / ".env"
config = dotenv_values(path)  # Import .env as dictionary

CLIENT_ID = config["CLIENT_ID"]
CLIENT_SECRET = config["CLIENT_SECRET"]
REDIRECT_URI = config["REDIRECT_URI"]

# URLS
AUTH_URL = 'https://accounts.spotify.com/authorize'
TOKEN_URL = 'https://accounts.spotify.com/api/token'
BASE_URL = 'https://api.spotify.com/v1/'

app = Flask(__name__)
app.secret_key = config['SECRET_KEY']  # Fix the secret key so that when reloaded, logins can persist.

login_manager = LoginManager()
login_manager.init_app(app)

user_store = {}

mydb = sqlite3.connect('mydb.db')
cursor = mydb.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS "users" (
                "UserID"	TEXT PRIMARY KEY,
                "refresh_token"	TEXT NOT NULL
            );''')
mydb.commit()
mydb.close()


class User(UserMixin):
    def __init__(self, u_id, refresh_token, access_token):
        self.u_id = u_id
        self.access_token = access_token
        self.refresh_token = refresh_token

    def get_id(self):
        return self.u_id


@login_manager.user_loader
def load_user(u_id):
    if user_store.get(u_id):
        return User(u_id, user_store[u_id]["refresh_token"], user_store[u_id]["access_token"])
    else:
        mydb = sqlite3.connect('mydb.db')
        cursor = mydb.cursor()
        cursor.execute('''SELECT * FROM users WHERE UserID=?''', (u_id,))
        result = cursor.fetchone()
        mydb.close()
        if result:
            access_token = refresh(result[1])
            if access_token:
                user_store[u_id] = {"access_token": access_token, "refresh_token": result[1]}
                return User(result[0], result[1], refresh(result[1]))
    return


def refresh(refresh_token):
    """Refresh access token."""

    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    res = requests.post(
        TOKEN_URL, auth=(CLIENT_ID, CLIENT_SECRET), data=payload, headers=headers
    )
    res_data = res.json()
    if res_data.get('error') or res.status_code != 200:
        return None

    return res_data.get('access_token')


@app.route('/', methods=['GET'])
def index():
    if current_user.is_authenticated:  # Logged in? Redirect.
        return redirect(url_for("playlist_picker"))
    return render_template('index.html')


@app.route('/login', methods=['GET'])
def login():
    if current_user.is_authenticated:  # Logged in? Redirect.
        return redirect(url_for("playlist_picker"))

    # Request authorization from user
    scope = 'playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private'

    state = secrets.token_hex(8)
    payload = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'state': state,
        'scope': scope,
    }

    res = make_response(redirect(f'{AUTH_URL}/?{urlencode(payload)}'))
    res.set_cookie('spotify_auth_state', state)

    return res


@app.route('/callback', methods=['GET', 'POST'])
def callback():
    error = request.args.get('error', None)
    code = request.args.get('code', None)
    state = request.args.get('state', None)
    stored_state = request.cookies.get('spotify_auth_state')

    # Check state
    if state is None or state != stored_state:
        print(f'Error message: {repr(error)}')
        print(f'State mismatch: {stored_state} != {state}')
        return redirect(url_for('logout'))

    # Request tokens with code we obtained
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
    }

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    res = requests.post(TOKEN_URL, auth=(CLIENT_ID, CLIENT_SECRET), data=payload, headers=headers)
    res_data = res.json()

    if res_data.get('error') or res.status_code != 200:
        print(
            'Failed to receive token:', res_data.get('error', 'No error information received.')
        )
        return redirect(url_for('logout'))

    refresh_token = res_data.get('refresh_token')
    access_token = res_data.get('access_token')
    headers = {'Authorization': f"Bearer {access_token}"}

    res = requests.get('https://api.spotify.com/v1/me', headers=headers)
    res2_data = res.json()

    if res.status_code != 200:
        print('Failed to get profile info:', res_data.get('error', 'No error message returned.'), res.status_code)
        return redirect(url_for('logout'))

    user_id = res2_data.get('id')

    user = User(user_id, refresh_token, access_token)

    mydb = sqlite3.connect('mydb.db')
    cursor = mydb.cursor()
    cursor.execute('''DELETE FROM users WHERE UserID=?''', (user_id,))
    cursor.execute('''INSERT INTO users 
                          ("UserID", "refresh_token")
                          VALUES (?, ?)''', (user_id, refresh_token))
    mydb.commit()
    mydb.close()

    user_store[user_id] = {"refresh_token": refresh_token, "access_token": access_token}

    login_user(user, remember=True)

    return redirect(url_for('playlist_picker'))


@app.route('/playlist_picker', methods=['GET', 'POST'])
def playlist_picker():
    if current_user.is_authenticated:
        if request.method == 'GET':
            headers = {'Authorization': f"Bearer {current_user.access_token}"}
            playlists = []
            next_url = 'https://api.spotify.com/v1/me/playlists?limit=50&offset=0'
            while next_url:
                res = requests.get(next_url, headers=headers)
                res_data = res.json()

                if res.status_code == 401:
                    print('Failed to get profile info:', res_data.get('error', 'No error message returned.'),
                          res.status_code)
                    new_token = refresh(current_user.refresh_token)
                    if new_token:
                        user_store[current_user.u_id]["access_token"] = new_token
                        current_user.access_token = new_token
                    else:
                        print('Failed to get access_token even after refresh.')
                        return redirect(url_for('logout'))

                elif res.status_code != 200:
                    print('Failed to get profile info:', res_data.get('error', 'No error message returned.'),
                          res.status_code)
                    return redirect(url_for('logout'))

                else:
                    for i in res_data.get('items', None):
                        if i:
                            if int(i["tracks"]["total"]) > 100:
                                playlists.append({
                                    "id": i["id"],
                                    "img": i["images"][-1]["url"] if i["images"] else "{{ url_for('static', "
                                                                                      "filename='no_img.png') }}",
                                    # Might be empty.
                                    "name": i["name"],
                                    "total_tracks": i["tracks"]["total"],
                                })
                    next_url = res_data.get('next', None)

            return render_template('playlist_picker.html', playlists=playlists)
    else:
        return redirect(url_for('index'))


@app.route('/playlist_picked', methods=['GET', 'POST'])
def playlist_picked():
    if current_user.is_authenticated:
        if request.method == 'POST':
            selected_playlist = request.form.get('playlist_option')
            playlist_id, num_tracks = selected_playlist.split(' | ')
            num_tracks = int(num_tracks)
            headers = {'Authorization': f"Bearer {current_user.access_token}"}
            picked_songs = []
            next_url = f'https://api.spotify.com/v1/playlists/{playlist_id}'
            random.seed(secrets.randbelow(100000))
            picked_tracks = deque(sorted(random.sample(range(0, num_tracks), 100)))

            while next_url and picked_tracks:
                res = requests.get(next_url, headers=headers)
                res_data = res.json()

                if res.status_code == 401:
                    print('Failed to get profile info:', res_data.get('error', 'No error message returned.'))
                    new_token = refresh(current_user.refresh_token)
                    if new_token:
                        user_store[current_user.u_id]["access_token"] = new_token
                        current_user.access_token = new_token
                    else:
                        return redirect(url_for('logout'))

                elif res.status_code != 200:
                    print('Failed to get profile info:', res_data.get('error', 'No error message returned.'))
                    return redirect(url_for('logout'))

                else:
                    if num_tracks > 100:
                        i = res_data.get('tracks')
                    else:
                        i = res_data
                    if i:
                        songs = i['items']
                        if songs:
                            while picked_tracks and picked_tracks[0] < 100:
                                picked_songs.append({
                                    "id": songs[picked_tracks[0]]["track"]["id"],
                                    # img might be empty.
                                    "img": songs[picked_tracks[0]]["track"]["album"]["images"][-1]["url"] if \
                                    songs[picked_tracks[0]]["track"]["album"]["images"] else \
                                    "{{ url_for('static', filename='no_img.png') }}",
                                    "name": songs[picked_tracks[0]]["track"]["name"],
                                    "artists": ", ".join([artist["name"] for artist in \
                                                songs[picked_tracks[0]]["track"]["artists"]])
                                })
                                picked_tracks.popleft()
                        next_url = i.get('next', None)

                        for j in range(len(picked_tracks)):
                            picked_tracks[j] -= 100
                        num_tracks -= 100

            user_store[current_user.u_id]["picked_songs"] = picked_songs

            return render_template('playlist_picked.html', picked_songs=picked_songs,
                                   selected_playlist=selected_playlist)
        return redirect(url_for('index'))
    else:
        return redirect(url_for('index'))


@app.route('/playlist_for_songs', methods=['GET', 'POST'])
def playlist_for_songs():
    if current_user.is_authenticated:
        if not user_store[current_user.u_id].get("picked_songs", None):
            return redirect(url_for('index'))
        else:
            headers = {'Authorization': f"Bearer {current_user.access_token}"}
            playlists = []
            next_url = 'https://api.spotify.com/v1/me/playlists?limit=50&offset=0'
            while next_url:
                res = requests.get(next_url, headers=headers)
                res_data = res.json()

                if res.status_code == 401:
                    print('Failed to get profile info:', res_data.get('error', 'No error message returned.'),
                          res.status_code)
                    new_token = refresh(current_user.refresh_token)
                    if new_token:
                        user_store[current_user.u_id]["access_token"] = new_token
                        current_user.access_token = new_token
                    else:
                        print('Failed to get access_token even after refresh.')
                        return redirect(url_for('logout'))

                elif res.status_code != 200:
                    print('Failed to get profile info:', res_data.get('error', 'No error message returned.'),
                          res.status_code)
                    return redirect(url_for('logout'))

                else:
                    for i in res_data.get('items', None):
                        if i:
                            playlists.append({
                                "id": i["id"],
                                "img": i["images"][-1]["url"] if i["images"] else "{{ url_for('static', "
                                                                                  "filename='no_img.png') }}",
                                # Might be empty.
                                "name": i["name"],
                                "total_tracks": i["tracks"]["total"],
                            })
                    next_url = res_data.get('next', None)

            return render_template('playlist_for_songs.html', playlists=playlists)
    else:
        return redirect(url_for('index'))


@app.route('/confirm_playlist_song', methods=['GET', 'POST'])
def confirm_playlist_song():
    if current_user.is_authenticated:
        if not user_store[current_user.u_id].get("picked_songs", None):
            return redirect(url_for('index'))
        else:
            if request.method == 'POST':
                selected_playlist = request.form.get('playlist_option', None)
                new_playlist_name = request.form.get('new_playlist_name', None)
                if selected_playlist:
                    selected_playlist_id, selected_playlist_name = selected_playlist.split(' || ')
                    return render_template('confirm_playlist_song.html',
                                           selected_playlist_id=selected_playlist_id,
                                           selected_playlist_name=selected_playlist_name)
                elif new_playlist_name:
                    return render_template('confirm_playlist_song.html',
                                           selected_playlist_id='',
                                           selected_playlist_name=new_playlist_name)
            return redirect(url_for('index'))
    else:
        return redirect(url_for('index'))


@app.route('/add_songs', methods=['GET', 'POST'])
def add_songs():
    if current_user.is_authenticated:
        if not user_store[current_user.u_id].get("picked_songs", None):
            return redirect(url_for('index'))
        else:
            if request.method == 'POST':
                playlist_id = request.form.get('playlist_id', None)
                playlist_name = request.form.get('playlist_name', None)
                if playlist_id and playlist_name:
                    if playlist_id == '':  # Create new playlist
                        headers = {'Authorization': f"Bearer {current_user.access_token}"}
                        next_url = f'https://api.spotify.com/v1/users/{current_user.u_id}/playlists'
                        payload = {
                            "name": playlist_name,
                            "description": "Custom playlist",
                            "public": False
                        }
                        res = requests.get(next_url, headers=headers, payload=payload)
                        res_data = res.json()

                        if res.status_code == 401:
                            print('Failed to get profile info:',
                                  res_data.get('error', 'No error message returned.'))
                            new_token = refresh(current_user.refresh_token)
                            if new_token:
                                user_store[current_user.u_id]["access_token"] = new_token
                                current_user.access_token = new_token
                            else:
                                return redirect(url_for('logout'))

                        elif res.status_code != 200:
                            print('Failed to get profile info:',
                                  res_data.get('error', 'No error message returned.'))
                            return redirect(url_for('logout'))

                        else:
                            new_playlist_id = res_data.get('id')
                            else:
                                i = res_data
                            if i:
                                songs = i['items']
                                if songs:
                                    while picked_tracks and picked_tracks[0] < 100:
                                        picked_songs.append({
                                            "id": songs[picked_tracks[0]]["track"]["id"],
                                            # img might be empty.
                                            "img": songs[picked_tracks[0]]["track"]["album"]["images"][-1]["url"] if \
                                                songs[picked_tracks[0]]["track"]["album"]["images"] else \
                                                "{{ url_for('static', filename='no_img.png') }}",
                                            "name": songs[picked_tracks[0]]["track"]["name"],
                                            "artists": ", ".join([artist["name"] for artist in \
                                                                  songs[picked_tracks[0]]["track"]["artists"]])
                                        })
                                        picked_tracks.popleft()
                                next_url = i.get('next', None)

                                for j in range(len(picked_tracks)):
                                    picked_tracks[j] -= 100
                                num_tracks -= 100

                    user_store[current_user.u_id]["picked_songs"] = picked_songs

                    selected_playlist_id, selected_playlist_name = selected_playlist.split(' || ')
                    return render_template('confirm_playlist_song.html',
                                           selected_playlist_id=selected_playlist_id,
                                           selected_playlist_name=selected_playlist_name)
                elif new_playlist_name:
                    return render_template('confirm_playlist_song.html',
                                           selected_playlist_id='',
                                           selected_playlist_name=new_playlist_name)
            return redirect(url_for('index'))
    else:
        return redirect(url_for('index'))


@app.route("/logout")
def logout():
    if current_user.is_authenticated:
        del user_store[current_user.u_id]
        mydb = sqlite3.connect('mydb.db')
        cursor = mydb.cursor()
        cursor.execute('''DELETE FROM users WHERE UserID=?''', (current_user.u_id,))
        mydb.commit()
        mydb.close()
        logout_user()
    return redirect(url_for("index"))


if __name__ == '__main__':
    app.run('0.0.0.0', 5005, ssl_context='adhoc', debug=True)
    # app.run('0.0.0.0', 5000, ssl_context=('cert.pem', 'key.pem'))
    mydb.close()