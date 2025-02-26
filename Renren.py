# -*- coding:utf-8 -*-
# Filename:Renren.py
#
from HTMLParser import HTMLParser
from Queue import Empty, Queue
from re import match
from urllib import urlencode
from opencv_face import face_detect
import os, re, json, sys
import threading, time
import urllib, urllib2, socket
import shelve
import logging, logging.handlers

def get_logger(handler = logging.StreamHandler()):
    import logging
    LOG_FILE = './run.log'

    filehandler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes = 1024*1024, backupCount = 5)
    logger = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler.setFormatter(formatter)
    filehandler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.addHandler(filehandler)    
    logger.setLevel(logging.NOTSET)
    return logger

logger = get_logger() 
GlobalShelveMutex = threading.Lock() 
TaskListFilename = "TaskList.bin"

# 避免urllib2永远不返回
socket.setdefaulttimeout(20)

class RenrenRequester:
    '''
    人人访问器
    '''
    LoginUrl = 'http://www.renren.com/Login.do'

    def CreateByCookie(self, cookie):
        logger.info("Trying to login by cookie")
        cookieFile = urllib2.HTTPCookieProcessor()
        self.opener = urllib2.build_opener(cookieFile)
        self.opener.addheaders = [('User-agent', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.4 (KHTML, like Gecko) Chrome/22.0.1229.92 Safari/537.4'),
                                  ('Cookie', cookie),
                                  ]
        
        req = urllib2.Request(self.LoginUrl)

        try:
            result = self.opener.open(req)
        except:
            logger.error("CreateByCookie Failed", exc_info=True)
            return False

        if not self.__FindInfoWhenLogin(result):
            return False

        return True

    
    # 输入用户和密码的元组
    def Create(self, username, password):
        self.username = username
        self.password = password
        logger.info("Trying to login by password")
        loginData = {'email':username,
                'password':password,
                'origURL':'http://www.renren.com',
                'formName':'',
                'method':'',
                'isplogin':'true',
                'submit':'登录'}
        postData = urlencode(loginData)
        cookieFile = urllib2.HTTPCookieProcessor()
        self.opener = urllib2.build_opener(cookieFile)
        self.opener.addheaders = [('User-agent', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.4 (KHTML, like Gecko) Chrome/22.0.1229.92 Safari/537.4')]
        req = urllib2.Request(self.LoginUrl, postData)
        result = self.opener.open(req)

        if not self.__FindInfoWhenLogin(result):
            return False

        return True

    def __FindInfoWhenLogin(self, result):
        result_url = result.geturl()
        logger.info(result_url)
        
        rawHtml = result.read()
        # print(rawHtml)

        # 获取用户id
        useridPattern = re.compile(r'\'id\':\'(\d+?)\'')
        try:
            self.userid = useridPattern.search(rawHtml).group(1)
        except:
            # GOD DAMN V7!
            v7Pattern = re.compile(r'id : \"(\d+?)\"')
            try:
                self.userid = v7Pattern.search(rawHtml).group(1)
                v7TokenPattern = re.compile(r'requestToken : \'(\d+?)\'')
                v7RtkPattern = re.compile(r'_rtk : \'(.*?)\'')
                self.uiVersion = 'v7'
                self.requestToken = v7TokenPattern.findall(rawHtml)[0]
                self._rtk = v7RtkPattern.findall(rawHtml)[0]

                logger.info('Login renren.com(v7) successfully.')
                logger.info("userid: %s, token: %s, rtk: %s" % (self.userid, self.requestToken, self._rtk))
                self.__isLogin = True      
                return self.__isLogin
            except Exception, e:
                raise e
                print('Failed...')
                return False
        # 查找requestToken
        pos = rawHtml.find("get_check:'")
        if pos == -1: return False        
        rawHtml = rawHtml[pos + 11:]
        token = match('-\d+', rawHtml)
        if token is None:
            token = match('\d+', rawHtml)
            if token is None: return False
        self.requestToken = token.group()  

        # 查找_rtk
        pos = rawHtml.find("get_check_x:'")
        if pos == -1: return False        
        self._rtk = rawHtml[pos + 13:pos + 13 +8]

        logger.info('Login renren.com successfully.')
        logger.info("userid: %s, token: %s, rtk: %s" % (self.userid, self.requestToken, self._rtk))
        
        self.__isLogin = True      
        return self.__isLogin
    
    def GetRequestToken(self):
        return self.requestToken
    
    def GetUserId(self):
        return self.userid
    
    def Request(self, url, data = None):
        if self.__isLogin:
            if data:
                encodeData = urlencode(data)
                request = urllib2.Request(url, encodeData)
            else:
                request = urllib2.Request(url)

            count = 0
            while True:
                try:
                    count += 1
                    if count > 5:
                        break
                    result = self.opener.open(request)
                    url = result.geturl()
                    rawHtml = result.read()
                    break
                except (socket.timeout, urllib2.URLError):
                    logger.error("Request Timeout", exc_info=True)
                    continue
            return rawHtml, url
        else:
            return None
        
        
class RenrenPostMsg:
    '''
    RenrenPostMsg
        发布人人状态
        '''
    
    def Handle(self, requester, param):
        requestToken, userid, _rtk, msg = param
        newStatusUrl = 'http://shell.renren.com/' + str(userid) + '/status'
        print newStatusUrl
        statusData = {'content':msg,
                      'hostid':userid,
                    'requestToken':requestToken,
                      '_rtk':_rtk,
                      'channel':'renren'}
        postStatusData = urlencode(statusData)
        
        requester.Request(newStatusUrl, statusData)
        
        return True

        
class RenrenPostGroupMsg:
    '''
    RenrenPostGroupMsg
        发布人人小组状态
    '''        
    newGroupStatusUrl = 'http://qun.renren.com/qun/ugc/create/status'
    
    def Handle(self, requester, param):
        requestToken, groupId, msg = param
        statusData = {'minigroupId':groupId,
                    'content':msg,
                    'requestToken':requestToken}
        requester.Request(self.newGroupStatusUrl, statusData)


class RenrenFriendList:
    '''
    RenrenFriendList
        人人好友列表
    '''
    def Handler(self, requester, param):     
        friendUrl = 'http://friend.renren.com/groupsdata'
        rawHtml, url = requester.Request(friendUrl)
        # print(rawHtml)

        friendInfoPack = rawHtml
        # print(friendInfoPack)
        friendIdPattern = re.compile(r'"fid":(\d+).*?fgroup.*?,"fname":"(.*?)"')
        friendIdList = []
        for id in friendIdPattern.findall(friendInfoPack):
            friendIdList.append((id[0], id[1].decode('unicode-escape').encode('utf-8')))
            # print(id)
        
        return friendIdList        
    

class RenrenRelationship:
    '''
    RenrenFriendList
        人人好友关系抓取
        return: [{'id':, 'name':, 'friends':[(id,name)]}]
    '''
    def Handler(self, requester):  
        self.requester = requester
        friendIdList = self.__GetFriendList(self.requester.userid)
        data = []
        length = len(friendIdList)
        index = 1
        for item in friendIdList:
            print item[0], ' (%d,%d)' % (index, length)
            index += 1
            di = {}
            di['id'] = item[0]; di['name'] = item[1]
            di['friends'] = self.__GetFriendList(item[0])
            data.append(di)
        return data  

    def __GetFriendList(self, id):
        try:
            url = 'http://friend.renren.com/GetFriendList.do?curpage=%d&id=%s'
            rawHtml = self.requester.Request(url % (0, str(id)))[0]
            # print rawHtml
            getPagePattern = re.compile(r'<span class="break">.*?curpage=(\d+)',re.S)
            pages = getPagePattern.findall(rawHtml)[0]
            # print pages
            getFriendPattern = re.compile(r'<dd><a href.*?\?id=(\d+?)\">(.*?)</a>')
            friendsList = []
            for i in xrange(0,int(pages)+1):
                rawHtml = self.requester.Request(url % (i, str(id)))[0]
                # rawHtml = rawHtml.decode('utf-8')
                friendsList.extend(getFriendPattern.findall(rawHtml))
            return friendsList
        except Exception, e:
            logger.error('GetFriendList failed.')
    

def DownloadImage(img_url, filename, requester = None):
    count = 0
    # Retry until we get the right picture.
    while True:
        try:
            # 避免过多的重试
            count += 1
            if count > 3:
                logger.error("Too many times retry.")
                break
            
            if requester == None:            
                resp = urllib2.urlopen(img_url); # note: Python 2.6 has added timeout support.            
            else:
                resp = requester.opener.open(img_url)
            respHtml = resp.read();
            filename = filename+'.'+str(resp.info().getheader("Content-Type").split('/')[1])
            binfile = open(filename, "wb");
            binfile.write(respHtml);
            binfile.close();
            return filename
            # n, msg = urllib.urlretrieve(img_url, filename)
            # logger.info(n + " " + str(msg.type))
            # if "image" in msg.type: 
            #     break
        except:
            logger.error("Downloading %s is failed." % filename, exc_info=True)


class RenrenAlbumDownloader2012:
    '''单个相册的下载器
    '''

    class DownloaderThread(threading.Thread):
        def __init__(self, tasks_queue):
            threading.Thread.__init__(self)
            self.queue = tasks_queue

        def run(self):
            try:
                while not self.queue.empty():
                    logger.info("Queue size: %d" % self.queue.qsize())
                    img_url, filename = self.queue.get(block = False)

                    logger.info("Downloading %s." % filename)
                    filename = DownloadImage(img_url, filename)
                    # rect = face_detect(filename)
                    # if len(rect) == 0:
                    #     os.remove(filename)
                    # else:
                    #     logger.info("Detected faces...")
            except: 
                logger.error("Error occured in Downloader.", exc_info=True)

    def __init__(self, requester, userid, path, threadnum):
        self.requester = requester    
        self.threadnum = threadnum
        self.userid = userid
        self.path = path
        self.ownid = requester.GetUserId()

    def Handler(self):
        self.__DownloadOneAlbum(self.userid, self.path)
        
    def __GetPeopleNameFromHtml(self, rawHtml):
        '''解析html获取人名'''
        peopleNamePattern = re.compile(r'<title>(.*?)</title>')
        # 取得人名
        peopleName = peopleNamePattern.search(rawHtml).group(1).strip()
        peopleName = peopleName[peopleName.rfind(' ') + 1:]
        return peopleName

    def __GetAlbumsInfoFromHtml(self, rawHtml):
        '''获取相册名字以及地址
        返回元组列表（相册名，相册地址，相册id，照片个数，缩略图网址列表）
        '''
        # print(rawHtml)
        # raw_input()
        albumUrlPattern = re.compile(r'''<li>(.*?)photo-num">([0-9]+)</div>.*?href="(.*?)\?frommyphoto".*?<span class="album-name">(.*?)</span>''', re.S)
        thumbnailsPattern = re.compile(r'url\((.*?)\)')
        AlbumidPattern = re.compile(r'album-(.*)')

        albums = []
        for thumbnailHtml, photonums, album_url, album_name in albumUrlPattern.findall(rawHtml):
            thumbnails = thumbnailsPattern.findall(thumbnailHtml)
            album_name = album_name.strip()
            album_name = album_name.replace('<i class="privacy-icon picon-friend"></i>', '')
            album_name = album_name.replace('<i class="privacy-icon picon-custom"></i>', '')
            if album_name == '<span class="userhead">':
                album_name = u"头像相册"
            elif album_name == '<span class="phone">':
                album_name = u"手机相册"
            elif album_name.startswith('<i class="privacy-icon picon-password"></i>'):
                continue
            elif album_name == '<span class="password">': # 有密码，跳过
                continue
            logger.info("album_url: [%s]  album_name: [%s] num: [%s]" % (album_url, album_name, photonums))
            albumid = AlbumidPattern.findall(album_url)[0]
            albums.append((album_name, album_url, albumid, photonums, thumbnails))

        return albums

    def __GetImgUrlsInAlbum(self, album_url):
        album_url += "/bypage/ajax?curPage=0&pagenum=100" # pick 100 pages which has 20 per page
        rawHtml, url = self.requester.Request(album_url)            
        rawHtml = unicode(rawHtml, "utf-8")

        img_urls = []
        try:
            data = json.loads(rawHtml)
            photoList = data['photoList'] 
            for item in photoList:
                img_urls.append((item['title'], item['largeUrl'])) 
        except ValueError:
            logger.error("Json Error", exc_info=True)
        finally:
            return img_urls

    def __EnsureFolder(self, path):
        if os.path.exists(path) == False:
            os.mkdir(path)
            return False
        else:
            return True   

    def __NormFilename(self, filename):
        filename = re.sub(ur"[\t\r\n\\/:：*?<>|]", "", filename)
        filename = filename.strip(". \n\r")
        return filename

    def __DownloadOneAlbum(self, userid, path):
        download_tasks = self.CreateTaskList()
        self.__Download(download_tasks)

    def CreateTaskList(self):
        userid = self.userid
        path = self.path
        path = path.decode('utf-8')
        self.__EnsureFolder(path)
        rootpath = os.path.join(path, self.ownid)
        rootpath = rootpath.decode('utf-8')
        self.__EnsureFolder(rootpath)
        
        albumsUrl = "http://photo.renren.com/photo/%s/album/relatives/ajax?offset=0&limit=10000" % userid
        # print(albumsUrl)

        # 打开相册首页，以获取每个相册的地址以及名字
        rawHtml, url = self.requester.Request(albumsUrl)            
        rawHtml = unicode(rawHtml, "utf-8")
        # print(rawHtml)

        albums = self.__GetAlbumsInfoFromHtml(rawHtml)
        # print(albums)

        try_count = 0
        while len(albums) == 0:
            logger.error("Empty album!")
            self.requester.Create(self.requester.username, self.requester.password)
            rawHtml, url = self.requester.Request(albumsUrl)            
            rawHtml = unicode(rawHtml, "utf-8")
            albums = self.__GetAlbumsInfoFromHtml(rawHtml)
            try_count+=1
            if try_count == 4:
                break

        if len(albums) == 0:
            logger.error("Empty album Empty album")
            sys.exit(1)

        # 更新path 欲下载的目标的用户id
        path = os.path.join(rootpath, userid)
        if self.__EnsureFolder(path) == True:
            pass
#                logger.info("Skipping user...") # ...断点续传...
#                return download_tasks
        
        #dump album name file
        albumfile = open(os.path.join(path,'album_name.txt'),'w')
        for name, url, albumid, photos, thumbnails in albums:
            logger.info('Getting imgurls for: ' + name + ' ' + str(albumid))
            albumfile.write(str(albumid) + ' ' + name.encode('utf-8') + '\n')
        albumfile.close()

        # 创建文件夹，以及下载任务 
        download_tasks = []
        for name, url, albumid, photos, thumbnails in albums:
            album_path = os.path.join(path, str(albumid))
            if self.__EnsureFolder(album_path) == True:
                pass
                logger.info("Skipping album...") # ...断点续传...
                continue

            index = 0
            img_urls = self.__GetImgUrlsInAlbum(url)
            for alt, img_url in img_urls:
                index += 1
                filename = os.path.join(album_path, str(index))
                download_tasks.append((img_url, filename))

        logger.info("Download Tasks size: %d." % len(download_tasks))

        return download_tasks

    def __Download(self, downloadTasks): 
        taskList = Queue()
        for item in downloadTasks:
            taskList.put(item)

        # 开始并行下载
        threads = []
        for i in xrange(self.threadnum):
            downloader = self.DownloaderThread(taskList)
            downloader.start()
            threads.append(downloader)

        for i, t in enumerate(threads):
            t.join() 

        logger.info("All Thread terminated")


class RenrenAlbumInfoGrabber:
    '''提供好友列表的每人的所有相册的概要下载
    '''

    class DownloaderThread(threading.Thread):
        def __init__(self, tasks_queue, requester = None):
            threading.Thread.__init__(self)
            self.queue = tasks_queue
            self.requester = requester

        def run(self):
            try:
                while not self.queue.empty():
                    logger.info("Queue size: %d" % self.queue.qsize())
                    img_url, filename = self.queue.get(block = False)

                    logger.info("Downloading %s." % filename)
                    DownloadImage(img_url, filename, self.requester)
            except: 
                logger.error("Error occured in Downloader.", exc_info=True)

    def __init__(self, requester, userIdList, path, threadnum):
        self.requester = requester    
        self.threadnum = threadnum
        self.userIdList = userIdList
        self.ownid = requester.GetUserId()
        self.path = path

    def Handler(self):
        self.__DownloadAlbums()
        
    def __GetPeopleNameFromHtml(self, rawHtml):
        '''解析html获取人名'''
        peopleNamePattern = re.compile(r'<title>(.*?)</title>')
        # 取得人名
        peopleName = peopleNamePattern.search(rawHtml).group(1).strip()
        peopleName = peopleName[peopleName.rfind(' ') + 1:]
        return peopleName

    def __GetAlbumsInfoFromHtml(self, rawHtml):
        '''获取相册名字以及地址
        返回元组列表（相册名，相册地址，相册id，照片个数，缩略图网址列表）
        '''
        # print(rawHtml)
        albumUrlPattern = re.compile(r'''<li>(.*?)photo-num">([0-9]+)</div>.*?href="(.*?)\?frommyphoto".*?<span class="album-name">(.*?)</span>''', re.S)
        thumbnailsPattern = re.compile(r'url\((.*?)\)')
        AlbumidPattern = re.compile(r'album-(.*)')

        albums = []
        for thumbnailHtml, photonums, album_url, album_name in albumUrlPattern.findall(rawHtml):
            thumbnails = thumbnailsPattern.findall(thumbnailHtml)
            album_name = album_name.strip()
            album_name = album_name.replace('<i class="privacy-icon picon-friend"></i>', '')
            album_name = album_name.replace('<i class="privacy-icon picon-custom"></i>', '')
            if album_name == '<span class="userhead">':
                album_name = u"头像相册"
            elif album_name == '<span class="phone">':
                album_name = u"手机相册"
            elif album_name.startswith('<i class="privacy-icon picon-password"></i>'):
                continue
            elif album_name == '<span class="password">': # 有密码，跳过
                continue
            logger.info("album_url: [%s]  album_name: [%s] num: [%s]" % (album_url, album_name, photonums))
            albumid = AlbumidPattern.findall(album_url)[0]
            albums.append((album_name, album_url, albumid, photonums, thumbnails))

        return albums

    def __EnsureFolder(self, path):
        if os.path.exists(path) == False:
            os.mkdir(path)
            return False
        else:
            return True


    def __NormFilename(self, filename):
        filename = re.sub(ur"[\t\r\n\\/:：*?<>|]", "", filename)
        filename = filename.strip(". \n\r")
        return filename

    def __DownloadAlbums(self):
        download_tasks = self.CreateTaskList()
        if len(download_tasks)>0:
            self.__Download(download_tasks)

    def CreateTaskList(self):
        userIdList = self.userIdList
        path = self.path
        path = path.decode('utf-8')
        self.__EnsureFolder(path)
        rootpath = os.path.join(path, self.ownid)
        rootpath = rootpath.decode('utf-8')
        self.__EnsureFolder(rootpath)
        
        download_tasks = []

        for userid in userIdList:
            albumsUrl = "http://photo.renren.com/photo/%s/album/relatives/ajax?offset=0&limit=10000" % userid
            # print(albumsUrl)
            # 更新path
            path = os.path.join(rootpath, userid)
            if self.__EnsureFolder(path) == True:
				pass
#                logger.info("Skipping user...") # ...断点续传...
#                return download_tasks


            # 打开相册首页，以获取每个相册的地址以及名字
            rawHtml, url = self.requester.Request(albumsUrl)      
            rawHtml = unicode(rawHtml, "utf-8")
#            print rawHtml.encode("gb18030")

            albums = self.__GetAlbumsInfoFromHtml(rawHtml)
#            print(albums)

            # 创建文件夹，以及下载任务
            for name, url, albumid, photos, thumbnails in albums:
                name = self.__NormFilename(name)
                album_path = os.path.join(path, albumid + " " + name)
                if self.__EnsureFolder(album_path) == True:
					pass
					logger.info("Skipping album...") # ...断点续传...
					continue

                index = 1
                for img_url in thumbnails:
                    name = str(index)
                    index += 1
                    filename = os.path.join(album_path, name)
                    download_tasks.append((img_url, filename))

        logger.info("Download Tasks size: %d." % len(download_tasks))

        return download_tasks

    def __Download(self, downloadTasks): 
        taskList = Queue()
        for item in downloadTasks:
            taskList.put(item)

        # 开始并行下载
        threads = []
        for i in xrange(self.threadnum):
            downloader = self.DownloaderThread(taskList, self.requester)
            threads.append(downloader)
            downloader.start()

        for i, t in enumerate(threads):
            t.join() 
            # logger.info("Thread %d ended" % i)

        logger.info("All Thread terminated")
        

class AllFriendAlbumsDownloader:
    '''下载所有好友的相册
    '''

    class DownloaderThread(threading.Thread):
        def __init__(self, db):
            threading.Thread.__init__(self)
            self.db = db

        def run(self):
            taskList = self.db["TaskList"]
            while len(taskList) > 0:
                try:
                    GlobalShelveMutex.acquire()
                    img_url, filename = taskList.pop() 
                except:
                    logger.error("Exception at Downloader.run()", exc_info=True)
                    continue
                finally:
                    GlobalShelveMutex.release()

                DownloadImage(img_url, filename)

                try:
                    GlobalShelveMutex.acquire()
                    self.db['DoneTask'].add(img_url)
                finally:
                    GlobalShelveMutex.release()


    class TaskListThread(threading.Thread):
        def __init__(self, taskList):
            threading.Thread.__init__(self)
            self.tastList = taskList

        def run(self):
            pass
                

    def Handler(self, requester, path, threadnum=20):
        self.requester = requester
        db = shelve.open(TaskListFilename, writeback = True)
        
        if not db.has_key("TaskList"):
            db["TaskList"] = []
        if not db.has_key("DoneTask"):
            db["DoneTask"] = set()

        logger.info("Task list length: %d" % len(db["TaskList"]))

        if len(db["TaskList"]) == 0: 
            friendsList = RenrenFriendList().Handler(self.requester, None)
            logger.info("Friend List length: %d" % len(friendsList))

            logger.info("Start creating the task list.")
            totalTaskList = []
            for userid, name in friendsList:
                downloader = RenrenAlbumDownloader2012(self.requester, userid, path, threadnum)
                taskList = downloader.CreateTaskList()
                totalTaskList.extend(taskList)
                
            doneSet = db["DoneTask"]
            db["TaskList"] = [item for item in totalTaskList if item[0] not in doneSet]
        else:
            logger.info("There is remain task, resume to download them.")

        threads = []
        for i in xrange(threadnum):
            downloader = self.DownloaderThread(db)
            downloader.start()
            threads.append(downloader)

        for i, t in enumerate(threads):
            logger.info("Thread %d ended" % i)
            t.join() 

        logger.info("All Thread terminated")

        
class SuperRenren:
    '''
    SuperRenren
        用户接口
    '''
    # 创建
    def Create(self, username, password):
        self.requester = RenrenRequester()
        if self.requester.Create(username, password):
            self.__GetInfoFromRequester()
            return True
        return False

    def CreateByCookie(self, cookie):
        self.requester = RenrenRequester()
        if self.requester.CreateByCookie(cookie):
            self.__GetInfoFromRequester()
            return True
        return False

    def __GetInfoFromRequester(self):
        self.userid = self.requester.userid
        self.requestToken = self.requester.requestToken
        self._rtk = self.requester._rtk

    # 发送个人状态
    def PostMsg(self, msg):
        poster = RenrenPostMsg()
        poster.Handle(self.requester, (self.requestToken, self.userid, self._rtk, msg))

    # 发送小组状态        
    def PostGroupMsg(self, groupId, msg):
        poster = RenrenPostGroupMsg()
        poster.Handle(self.requester, (self.requestToken, groupId, msg))

    def GetFriendList(self): 
        friendsList = RenrenFriendList().Handler(self.requester, None)
        return friendsList

    def GetRelationship(self):
        relationDict = RenrenRelationship().Handler(self.requester)
        return relationDict

    # 下载相册
    def DownloadAlbum(self, userId, path = 'albums', threadnum=20):       
        downloader = RenrenAlbumDownloader2012(self.requester, userId, path, threadnum)
        downloader.Handler()

    # 下载相册摘要
    def DownloadAlbumInfo(self, userIdList, path = 'albums', threadnum=20):
        downloader = RenrenAlbumInfoGrabber(self.requester, userIdList, path, threadnum)
        downloader.Handler()

    # 自动下载所有好友相册
    def DownloadAllFriendsAlbums(self, path = 'albums', threadnumber = 50):
        downloader = AllFriendAlbumsDownloader()
        downloader.Handler(self.requester, path, threadnumber)
