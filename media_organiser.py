from pymediainfo import MediaInfo
import sys, os, pymongo, hashlib, configparser, xxhash, locale, argparse, json, logging
from guessit import guessit
from imdbpie import Imdb

imdb = Imdb(anonymize=True) # to proxy requests
REBUILD_SIDECAR = False

# Setting default hasher - can be changed with command line


# Let's configure the locale
locale.setlocale(locale.LC_ALL, 'en_US') # We use this for number formating while we count blocks
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

class FileManagement():

    def validate_sidecar_file(sidecar_file):
        try:
            fact_size = sidecar_file['quick_facts']['file_size']
            fact_name = sidecar_file['quick_facts']['file_name']
            fact_last_known = sidecar_file['quick_facts']['last_known_location']
            return True
        except KeyError: # We couldn't find the keys we need. Let's rebuild it
            print("--> There seems to be some issue with the sidecar file. Let me fix that for you.")
            return False

        # Ok, so we got the key's, now let's make sure they are all valid values
        # attached to the key's



    def hashfile(fullpath_to_mediafile):
        """ Hashes any given file using xxhash (https://cyan4973.github.io/xxHash/)

            Args:
                fullpath: The full path, including file name to the file to be hashed

            Returns:
                A String hash value
        """
        # Setting the block size
        hasher = xxhash.xxh64() #Set the hasher
        BLOCKSIZE = 65536

        size = os.path.getsize(fullpath_to_mediafile)
        blocks = int(size / BLOCKSIZE)

        with open(fullpath_to_mediafile, 'rb') as afile:
            buf = afile.read(BLOCKSIZE) #Read one block
            while len(buf) > 0: #
                hasher.update(buf)
                buf = afile.read(BLOCKSIZE)
                if (blocks % 1000) == 0: # Only print every 1000 blocks so not to spam the terminal
                    print("Blocks to go:", locale.format("%d", blocks, grouping=True), end="\r", flush=True)
                blocks -= 1

        return hasher.hexdigest()

def find_imdb_ID_from_title(filename):
    # First, let's extract the name of the movie and it's year
    nameDict = guessit(filename)
    try:
        title = nameDict['title']
        year = nameDict['year']
    except KeyError:
        print('This file "' + filename + '" seems oddly named. Please follow [title] [year] format')
        return None
    imdbResult = imdb.search_for_title(title)
    for movie in imdbResult:
        if title == movie['title'] and str(year) == movie['year']:
            print('Match found')
            return movie['imdb_id']

    return None

def scanMovies(fd):
    """ Goes through the directory structure seaching for specific files
    matching the extention mentioned in the list
    """

    for dir_path,subpaths,files in os.walk(fd):
        for file in files:
            extension = os.path.splitext(file)[1].lower()
            if extension in ['.mkv', '.mp4', '.avi', '.mov']:
                fullpath = os.path.abspath(dir_path) + "/" + file
                # Get the media info. This an take a while
                scanMediaInfo(dir_path, fullpath, file)
            elif extension in ['.ts', '.m2ts']:
                fullpath = os.path.abspath(dir_path) + "/" + file
                filesize = os.path.getsize(fullpath)
                if filesize > 20000000000:
                    convert_to_mkv(dir_path, fullpath, file)



def convert_to_mkv(path, fullpath, filename):
    print('Video convertion is not yet done. In progress since 17 May 2017')
    # Let's establish what we are working with first. Is bluray structure intact or just a odd format.
    base_path = os.path.basename(path)
    if base_path == 'STREAM': # Bluray structure is intact it seems [Basefolder]/BDMV/STREAM/mediafile.m2ts
        print('Bluray rip convertion')
    else:
        print('Asuming we are in a ripped directory')

def scanMediaInfo(path, fullpath, filename):
    """ Parses the media info of the file. If, new, we will hash it and add it to the library.
    We use the MKV FileUID as our guide if it's new or now. Hashing is just to slow for a quick check.

        Args:   path: The URI of the file
                fullpath: The URI + Filename
                filename: the file name of the media we try to scan

    """
    filelen = len(filename)
    print('=======================' + "=" * filelen)
    print('Scanning Media info on', filename)
    print('=======================' + "=" * filelen)
    # Getting the media info

    # Let's just have a quick check if we seen this file before
    filesize = os.path.getsize(fullpath)
    result = is_this_file_known(filename=filename, path=path, filesize=filesize)

    if result == False or REBUILD_SIDECAR ==True: #We couldn't find the sidecar file. Doing a full update
        media_info = MediaInfo.parse(fullpath)

        # We need to add some metadata here so we can do some quick lookups
        media_json = json.loads(media_info.to_json(), parse_int=str)

        if 'unique_id' in media_json['tracks'][0]:
            media_xxhash = media_json['tracks'][0]['unique_id']
        else:
            media_xxhash = FileManagement.hashfile(fullpath)

        imdb_id = find_imdb_ID_from_title(filename)
        media_json['quick_facts'] = {'file_size':filesize,
                                     'file_hash': media_xxhash,
                                     'file_name': filename,
                                     'last_known_location' : fullpath,
                                     'imdb_id': imdb_id}
        # Save it to a file next to the media file for later use
        sidecar_file = open(path + '/' + filename + '_sidcar.json', 'w')
        sidecar_file.write(json.dumps(media_json))
        insertMediaFile(media_json)
    else: #Hey, we know this one, no need to do anything about this.
    # Save it to a file next to the media file for later use
        print('Seems like we have scanned this before.\n--> If you want to scan it again, remove the _sidecar file next to the original file')
        print('You can find it here:\n')
        print(path + filename + '_sidcar.json')
        print('\n')
        print('--> Will still try to add it to the DB just in case we deleted it at some point.')
        sidecar_file = open(path + '/' + filename + '_sidcar.json', 'r')
        insertMediaFile(json.load(sidecar_file))

"""

So sorry for the deep iffing here. Will fix it after lunch... :D
"""
def is_this_file_known(filename, filesize, path):
    sidecar_uri = path + '/' + filename + '_sidcar.json' #Path to the sidecar file
    if os.path.isfile(sidecar_uri):
        sidecar_file = json.load(open(sidecar_uri, 'r')) # We found it, lets look inside
        try:
            fact_size = sidecar_file['quick_facts']['file_size']
            fact_name = sidecar_file['quick_facts']['file_name']
            fact_last_known = sidecar_file['quick_facts']['last_known_location']
        except KeyError: # We couldn't find the keys we need. Let's rebuild it
            print("--> There seems to be some issue with the sidecar file. Let me fix that for you.")
            return False
        if fact_size != filesize: # We check filesize first since that would qualify for a full rescan no matter what the name is of the file
            print("--> The filesize doesn't match the sidecar file info. We should scan again.. \n----")
            return False #Sidecar file exist but the basic info is not matching
        elif fact_name != filename: #Ok, so the name doesn't match but the size does. Maybe we renamed both mediafile and the sidecar. Let's verify this.
            print("--> The filename doesn't match the sidecar file info. Let's check the hash. Please wait... \n----")
            file_hash = FileManagement.hashfile(path + "/" + filename)
            fact_hash = sidecar_file['quick_facts']['file_hash']
            print(file_hash +  " + " + fact_hash)
            if fact_hash == file_hash:
                print("--> Seems like the file is the same but renamed. Let me update that for you!")
                sidecar_file['quick_facts']['file_name'] = filename
                f = open(sidecar_uri, 'w')
                f.write(json.dumps(sidecar_file));
                return True
            else:
                print("--> The xxhash doesn't match. Something has changed so let's re-scan it all")
                return False #Sidecar file exist but the basic info is not matching
        elif fact_last_known != os.path.abspath(path + '/' + filename):
            print('--> The location seem to have change. Rebuiding the file. I know it a pain, I will make this faster later')
            return False
        else: # Everything is good. Lets just skip this file.
            return True
    else:
        print("--> Can't find the sidecar file. Assuming this is a new file, or renamed\n----")
        return False #Can't even find the sidecar file


def insertMediaFile(file_data):
    """ Inserts a record in the MongoDB

    """
    # client = pymongo.MongoClient('mongodb://arkalon:F463Rlund@cluster0-shard-00-00-if3vm.mongodb.net:27017,cluster0-shard-00-01-if3vm.mongodb.net:27017,cluster0-shard-00-02-if3vm.mongodb.net:27017/icecream?ssl=true&replicaSet=Cluster0-shard-0&authSource=admin')
    # db = client[db_name]
    client = pymongo.MongoClient(db_url,db_port)
    db = client[db_name]
    db.authenticate(db_username,db_password)
    # First, make sure there is no duplicate
    result = db.Movies.find({'quick_facts.file_hash' : file_data['quick_facts']['file_hash']})
    if result.count() != 0:
        print('--> Hey! We already have this bad boy in the database. Will not add it twice.')
        print('\n\n')
    else:
        db.Movies.insert_one(file_data)
        print('--> File has been added to the DB and a sidcar file to the filesystem.')
        print('\n\n')

def configure_application():
    # Let's configure stuff
    config = configparser.RawConfigParser()

    #First, let's make sure we have a config file. If not, create a template and quit
    is_configured = os.path.isfile('media_organiser.cfg')
    if is_configured:
        config.read('media_organiser.cfg')
        # Configure mLab Database
        global db_name
        global db_port
        global db_url
        global db_username
        global db_password

        db_name = config.get('mLab','db_name')
        db_port = config.getint('mLab','db_port')
        db_url = config.get('mLab','db_url')
        db_username = config.get('mLab','username')
        db_password = config.get('mLab','password')
    elif os.path.isfile('media_organiser_template.cfg'):
        sys.exit('--> Did you forget to rename the template file to "media_organiser.cfg"?')
    else:
        f = open('media_organiser_template.cfg', mode='w')
        f.write("[mLab]\ndb_url = \ndb_port = \nusername = \npassword = \ndb_name = ")
        sys.exit("--> App has no config file. Creating a template and quitting")


if __name__ == "__main__":
    configure_application()
    # Setup the Argument Parser
    parser = argparse.ArgumentParser(description='Documentation of all media files as you have. Will get some media details and hash them.')
    parser.add_argument('media', help='Where your mediafiles are')
    parser.add_argument('-c', '--config', help='Location of the config file. Default: Same directory as main file [media_organiser.cfg]')
    parser.add_argument('-m', '--remux', help='[Not working yet!!] If selected, we will remux non-mkv to mkv format.')
    parser.add_argument('-r', '--rebuild', action="store_true" ,help='Rebuild ALL sidecar files')
    args = parser.parse_args()
    REBUILD_SIDECAR = args.rebuild

    if REBUILD_SIDECAR:
        response = input('Are you sure you want to rebuild ALL sidecar files? (y/n) --> ')
        if response.lower() == 'y':
            scanMovies(args.media)
        else:
            print('Oh, did you forget to remove the "-r" flag?')
    else:
        scanMovies(args.media)
    print('================================')
    print('        Scan finished.          ')
    print('================================')
