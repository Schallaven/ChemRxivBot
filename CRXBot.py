#!/usr/bin/env python3

import argparse
import json
import os
import requests
import sys
import tweepy
import time
from datetime import datetime

doiRootURL = "https://doi.org/"

def write_log(message):
    print(message)
    with open('activity_log.txt', 'a') as f:
        f.write(str(datetime.now()) + ' ' + message + '\n')
        
def get_preprint_image_url(files):
    ###Files should be a list of dictionaries for each files
    if type(files) is not list:
        return ""
    
    for preprint_file in files:
        if preprint_file['is_link_only']:
            continue
        
        filename = preprint_file['name'].lower()

        if filename.endswith('.png') or filename.endswith('.jpg'):
            return preprint_file['download_url']
    
    return ""
    
        
def tweet_image(url, message, usetwitter = True):  
    ###Takes in a file from a URL, downloads it,
    ###tweets it with the given message, then deletes the file
    ###Should there be no url given or there be an error with
    ###the download, then just tweet without image
    include_image = False
    filename = 'temp.png'
    
    if len(url) > 0:
        request = requests.get(url, stream=True)
        if request.status_code == 200:
            with open(filename, 'wb') as image:
                for chunk in request:
                    image.write(chunk)
            include_image = True
        else:
            write_log("Error, couldn't download image. Continue without.")
        
    if usetwitter:
        if include_image:        
            twitter_api.update_with_media(filename, status=message)
            os.remove(filename)
        else:
            twitter_api.update_status(message)  
    else:
        write_log(f'Offline-Tweeting due to user request (--notwitter on command line).')   
        if include_image:
            filesize = os.path.getsize(filename) // 1024 # in Kilobytes
            write_log(f'Tweet includes image of {filesize} KBytes.')
    
    lenmessage = len(message)
    write_log(f'Tweet successful. {message} ({lenmessage} characters).')
    

def prepare_tweet(title, authors, preprintURL, tags):
    ## Tweet format : {TITLE} by {AUTHOR} {TAGS as HASHTAGS} \n\n {DOI URL} [thumbnail image]
    
    ## Tweet title
    tweetTitle = f'{title} by '

    ## Tweet author(s)
    ## Determines if the paper had more than one author and selectively appends 
    ## (or doesn't append) "& co-workers"
    tweetAuthors = authors[-1]['full_name']
    
    if len(authors) > 1:
        tweetAuthors += " & co-workers"

    ## Need to make sure the total length of the tweet is <280 characters
    ## An url is always 23 characters, no matter the length. We want to add
    ## two newline characters before the URL (23+2=25). Therefore, the length 
    ## we are checking for here is actually 280-25=255 characters.
    tweetText = tweetTitle + tweetAuthors
    
    ## Preprint keywords as Tweet hashtags
    ## This tries to include as many keywords as possible as hashtags
    for tag in tags:    
        hashtag = " #" + tag.lower().replace(' ', '-')
        
        if (len(tweetText) + len(hashtag)) <= 255:
            tweetText += hashtag
    
    ## Add URL (always 23 Tweet characters, no matter how long it is)
    tweetText += "\n\n" + preprintURL
    
    ## We guarantee more or less that this thing is <=280 characters long
    realtweetlength = len(tweetText) - len(preprintURL) + 23
    if realtweetlength > 280:
        return False
    
    return tweetText 

    ## For authors, enumerated as a list of dictionaries. Relevant key is full_name
    ## Possible to assess whether all authors can fit before deciding which to tweet?
    ## First author is not always appropriate, but neither is last.
    ## Going to start by just tweeting the last author and developing as needed

class chemRxivAPI:
    ## Class taken from FX Coudert's ChemRxiv.py https://github.com/fxcoudert

    """Handle figshare API requests, using access token"""

    base = 'https://api.figshare.com/v2'
    pagesize = 100

    def __init__(self, token):
        """Initialise the object and check access to the API"""

        self.token = token
        self.headers = {'Authorization': 'token ' + self.token}

        r = requests.get(f'{self.base}/account', headers=self.headers)
        r.raise_for_status()

    def request(self, url, method, params):
        """Send a figshare API request"""

        if method.casefold() == 'get':
            return requests.get(url, headers=self.headers, params=params)
        elif method.casefold() == 'post':
            return requests.post(url, headers=self.headers, json=params)
        else:
            raise Exception(f'Unknown method for query: {method}')

    def query(self, query, method='get', params=None):
        """Perform a direct query"""

        r = self.request(f'{self.base}/{query}', method, params)
        r.raise_for_status()
        return r.json()

    def query_generator(self, query, method='get', params={}):
        """Query for a list of items, with paging. Returns a generator."""

        n = 0
        while True:
            params.update({'limit': self.pagesize, 'offset': n})
            r = self.request(f'{self.base}/{query}', method, params)
            r.raise_for_status()
            r = r.json()

            # Special case if a single item, not a list, was returned
            if not isinstance(r, list):
                yield r
                return

            # If we have no more results, bail out
            if len(r) == 0:
                return

            yield from r
            n += self.pagesize

    def query_list(self, *args, **kwargs):
        """Query of a list of item, handling paging internally, returning a
        list. May take a long time to return."""

        return list(self.query_generator(*args, **kwargs))

    def all_preprints(self):
        """Return a generator to all the chemRxiv preprints"""

        return api.query_generator('articles?institution=259')

    def preprint(self, identifier):
        """Information on a given preprint"""

        return api.query(f'articles/{identifier}')

    def author(self, identifier):
        """Information on a given preprint"""

        return api.query(f'account/authors/{identifier}')

    def custom_fields_as_dict(self, doc):
        """Retrieve chemRxiv custom fields as a dictionary"""

        return {i['name']: i['value'] for i in doc['custom_fields']}

    def search_authors(self, criteria):
        """Search for authors"""

        return api.query('account/authors/search', method='POST', params=criteria)

    def search_preprints(self, criteria):
        """Search for preprints"""

        p = {**criteria, 'institution': 259}
        return api.query_list('articles/search', method='POST', params=p)
    
    def files(self, identifier):
        """Files of given preprint"""
        
        return api.query(f'articles/{identifier}/files')



###############################################################
##                   PARAMETER EVALUATION                    ##
###############################################################
parser = argparse.ArgumentParser(
			description = 'ChemRxiv Twitterbot that automates tweeting new preprints.')

parser.add_argument('-v', '--version', help = 'prints version information', action='version', 
                    version='CRXBot 1.0')

parser.add_argument('-n', '--notwitter', help = 'Do not use Twitter API. useful for debugging '
                    'without publishing actual Tweets.', action = 'store_false', 
                    dest = 'usetwitter') 

args = vars(parser.parse_args())


###############################################################
##                      START UP ROUTINES                    ##
###############################################################

## Pull in keys

# Store keys, secrets & tokens in CRX_keys.text
# Format the file like this, with no additional text in the document:
# twitKey
# twitSecret
# twitToken
# twitToken_secret
# chemRxiv_token

## Read in CRX_keys.txt as a list
CRX_keys = []
with open('CRX_keys.txt', 'r') as f:
    CRX_keys = list(f)

#clean up the keys
for i in range(len(CRX_keys)):
    temp = CRX_keys[i]
    CRX_keys[i] = temp.strip('\n')
write_log("Keys, tokens and secrets successfully loaded...")

twitKey = CRX_keys[0]
twitSecret = CRX_keys[1]
twitToken = CRX_keys[2]
twitToken_secret = CRX_keys[3]
chemRxiv_token = CRX_keys[4]

## Prep Twitter
if args['usetwitter']:
    twitter_auth = tweepy.OAuthHandler(twitKey, twitSecret)
    twitter_auth.set_access_token(twitToken, twitToken_secret)
    twitter_api = tweepy.API(twitter_auth)
    twitterUser = twitter_api.me().screen_name
    write_log(f'Authenticated as Twitter user {twitterUser} successfully.')
else:
    write_log(f'Skipped Twitter authentification due to user request'
               ' (--notwitter on command line).')

## Connect to Figshare
try:
    api = chemRxivAPI(chemRxiv_token)
except requests.exceptions.HTTPError as e:
    write_log(f'Authentication did not succeed. Token was: {chemRxiv_token}')
    write_log(f'Error: {e}')
    sys.exit(1)
write_log("Authenticated with Figshare.")

## Read in the ID Log as a list
id_log = []
with open('id_log.txt', 'r') as f:
    id_log = list(f)

#clean up the id_log
for i in range(len(id_log)):
    temp = id_log[i]
    id_log[i] = temp.strip('\n')
write_log("ID Log successfully loaded...")

###############################################################
##                      BOT STARTS HERE                      ##
###############################################################

# pull down preprints
doc = api.all_preprints()
numberPreprints = sys.getsizeof(doc)
write_log(f'Retrieved {numberPreprints} preprints. Beginning search for new content...')

preprints_added = 0
preprints_tweeted = 0
preprints_tweeted_FAILED = 0

# iterate through the preprints

for i in range(numberPreprints):
        # load preprint data
        l = next(doc)

        preprint_id = str(l['id'])


        # only proceed if the preprint has not been processed previously
        if preprint_id in id_log:
            pass
        else:
            write_log("New preprint found!")

            ## Pull the full dataset for the preprint
            ## (for some reason the general pull doesn't
            ## get the author information, so let's only
            ## enumerate this for preprints we're going to
            ## actually tweet)

            ## Need to provide accomodations to not tweet revisions.
            ## Metadata field 'version' likely holds what we would need to exclude.

            current_preprint = api.preprint(preprint_id)

            ## Collect the information needed for the tweet

            preprint_title = current_preprint['title']

            ## Extracting the author data takes a bit more work
            authorData = current_preprint['authors']

            ## Format the URL based off of the doi

            preprintURL = doiRootURL + current_preprint['doi']

            ## Grab the thumbnail url
            ## Modification: use the first good image in the files of the preprint
            thumbnailURL = get_preprint_image_url(api.files(preprint_id))
            
            ## Get keywords of preprint
            tags = current_preprint['tags']
            

            ## Prepare the tweet; throw an error if it it's too long
            ## Future note: what should we do when they are too long?
            ## How often will that happen? Should it notify me somehow?
            ## Let's wait and see...

            tweetText = prepare_tweet(preprint_title, authorData, preprintURL, tags)

            if tweetText == False:
                write_log(f'NOTICE: Could not tweet preprint at {preprintURL}, please check manually.')
                preprints_tweeted_FAILED += 1
            else:
                write_log(f'Submitting {preprint_id} to Twitter...')
                tweet_image(thumbnailURL, tweetText, args['usetwitter'])
                preprints_tweeted += 1


            write_log("Committing ID to log...")
            with open('id_log.txt', 'a') as f:
                f.write(preprint_id + '\n')
            write_log(f'Wrote {current_preprint["id"]} to log')
            preprints_added += 1
            
            if args['usetwitter']:
                time.sleep(1800) # Currently set to wait 30 sec after each tweet for 
                                 # testing purposes. Should be increased when running for real 
                                 # (likely to 1800).
                                 
            ## Need to set a better solution for looping through the script. Considering Daemon or Cron
write_log(f'All preprints checked. Processed {preprints_added} new preprints. Tweeted {preprints_tweeted}, failed to tweet {preprints_tweeted_FAILED}.')
