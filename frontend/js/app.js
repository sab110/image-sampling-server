// Client ID and API key from the Developer Console
const CLIENT_ID = '384701708058-hsgh6f3t0vs6uqrgm35p6qm5vei1ovcl.apps.googleusercontent.com'; // Your Client ID
const API_KEY = 'AIzaSyDzWoQYVewhP0hxHLzQLLvtpE3scBvBsLk'; // Your API Key

// Authorization scopes required by the API
const SCOPES = 'https://www.googleapis.com/auth/drive';

// Variables
let tokenClient;
let accessToken = null;
let folderId = '';
let folderName = '';
let totalImages = 0;

// On load, called to load the auth2 library and API client library.
function handleClientLoad() {
    gapi.load('client:picker', initClient);
}

function initClient() {
    gapi.client.setApiKey(API_KEY);
    gapi.client.load('drive', 'v3', () => {
        console.log('Drive API loaded.');
    });

    // Initialize the token client
    tokenClient = google.accounts.oauth2.initTokenClient({
        client_id: CLIENT_ID,
        scope: SCOPES,
        callback: (tokenResponse) => {
            const loginStatus = document.getElementById('login-status');
            if (tokenResponse.error) {
                console.error('Error obtaining access token:', tokenResponse);
                // Display login failure message
                loginStatus.innerHTML = '<div class="alert alert-danger">Login failed. Please try again.</div>';
                return;
            }
            accessToken = tokenResponse.access_token;
            document.getElementById('signin-button').style.display = 'none';
            document.getElementById('signout-button').style.display = 'inline-block';
            document.getElementById('folder-section').style.display = 'block';
            // Display login success message
            loginStatus.innerHTML = '<div class="alert alert-success">Login successful!</div>';
        },
    });
}

// Sign in the user upon button click.
function handleAuthClick() {
    tokenClient.requestAccessToken({ prompt: '' });
}

// Sign out the user upon button click.
function handleSignoutClick() {
    // Remove the access token
    accessToken = null;
    // Hide the folder section
    document.getElementById('folder-section').style.display = 'none';
    // Show the sign-in button, hide the sign-out button
    document.getElementById('signin-button').style.display = 'inline-block';
    document.getElementById('signout-button').style.display = 'none';
    // Clear the login status
    document.getElementById('login-status').innerHTML = '';
    // Clear the selected folder name
    document.getElementById('selected-folder-name').textContent = '';
    // Clear the process section and status
    document.getElementById('process-section').style.display = 'none';
    document.getElementById('status').innerHTML = '';
    // Revoke token
    google.accounts.oauth2.revoke(accessToken, () => {
        console.log('Access token revoked.');
    });
}

// Create and render a Picker object for selecting folders.
function createPicker() {
    if (accessToken) {
        const view = new google.picker.DocsView(google.picker.ViewId.FOLDERS)
            .setSelectFolderEnabled(true);

        const picker = new google.picker.PickerBuilder()
            .setAppId('384701708058') // Replace with your Cloud Project Number
            .setOAuthToken(accessToken)
            .addView(view)
            .setCallback(pickerCallback)
            .build();

        picker.setVisible(true);
    } else {
        console.error('No access token available.');
    }
}

// Called when a folder has been selected in the Google Picker.
function pickerCallback(data) {
    if (data.action === google.picker.Action.PICKED) {
        const doc = data.docs[0];
        folderId = doc.id;
        folderName = doc.name;
        document.getElementById('selected-folder-name').textContent = 'Selected Folder: ' + folderName;
        checkFolderImages();
    }
}

// Check if the folder contains less than 100 images.
function checkFolderImages() {
    gapi.client.drive.files.list({
        q: `'${folderId}' in parents and mimeType contains 'image/' and trashed=false`,
        fields: 'files(id, name)',
        pageSize: 101, // One more than MAX_IMAGES to check the count
    }).then(function(response) {
        const files = response.result.files;
        totalImages = files.length;
        if (totalImages === 0) {
            alert('The selected folder contains no images.');
            document.getElementById('process-section').style.display = 'none';
        } else if (totalImages > 100) {
            alert('The selected folder contains more than 100 images.');
            document.getElementById('process-section').style.display = 'none';
        } else {
            document.getElementById('process-section').style.display = 'block';
        }
    }, function(error) {
        console.error('Error:', error);
    });
}

// Send data to backend to process images.
function processImages() {
    const upsampleCount = parseInt(document.getElementById('upsample-count').value);
    if (isNaN(upsampleCount) || upsampleCount < 1 || upsampleCount > 3) {
        alert('Please enter a valid upsample count between 1 and 3.');
        return;
    }

    document.getElementById('status').innerHTML = '<p>Processing images, please wait...</p>';

    fetch('https://image-sampling-server-384701708058.us-central1.run.app/api/process_images', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            folderId: folderId,
            accessToken: accessToken,
            upsampleCount: upsampleCount
        })
    })
    .then(response => {
        console.log("Response status:", response.status);  // Add this for debugging
        return response.json();
    })
    .then(data => {
        if (data.error) {
            document.getElementById('status').innerHTML = '<div class="alert alert-danger">Error: ' + data.error + '</div>';
        } else {
            document.getElementById('status').innerHTML = '<div class="alert alert-success">' + data.message + '</div>';
        }
    })
    .catch(error => {
        console.error('Error:', error);
        document.getElementById('status').innerHTML = '<div class="alert alert-danger">An error occurred while processing images.</div>';
    });
    
}
