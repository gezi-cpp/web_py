#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__='by花'

import markdown2
from WebFrame import get,post
from Instance_Model import User,Comment,Blog,next_id
import asyncio,re,time,json,logging,hashlib,base64
from aiohttp import web
from config import configs
from apis import APIValueError,APIResourceNotFoundError,Page

COOKIE_NAME='awesession'
_COOKIE_KEY=configs.session.secret

def text2html(text):
    lines=map(lambda s:'<p>%s</p>'%s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;'),filter(lambda s:s.strip()!='',text.split('\n')))
    return ''.join(lines)

#用户浏览页面  
@get('/')
async def index(*,page='1'):
    page_index=get_page_index(page)
    num=await Blog.findNumber('count(id)')
    page=Page(num)
    if num==0:
        blogs=[]
    else:            
        blogs=await Blog.findAll(orderBy='created_at desc',limit=(page.offset,page.limit))
    return{
        '__template__':'blogs.html',
        'blogs':blogs,
        'page':page    
    }
    
@get('/blog/{id}')
async def get_blog(id):
    blog=await Blog.find(id)
    comments=await Comment.findAll('blog_id=?',[id],orderBy='created_at desc')
    for c in comments:
        c.html_content=text2html(c.content)
    blog.html_content=markdown2.markdown(blog.content)
    return{
        '__template__':'blog.html',
        'blog':blog,
        'comments':comments
    }            

              
@get('/register')
def register(request):
    return{
        '__template__':'register.html'
    }      
     
@get('/signin')
def signin(request):
    return{
        '__template__':'signin.html'
    }
    
@get('/signout')
def signout(request):
    referer=request.headers.get('Referer')
    r=web.HTTPFound(referer or '/')
    r.set_cookie(COOKIE_NAME,'-deleted-',max_age=0,httponly=True)
    logging.info('user signed out.')
    return r

#后端API             
@get('/api/users')  #获取用户
async def api_get_users(*,page='1'):
    page_index=get_page_index(page)
    num=await User.findNumber('count(id)')
    p=Page(num,page_index)
    if num==0:
        return dict(page=p,users=())
    users=await User.findAll(orderBy='created_at desc',limit=(p.offset,p.limit))
    for u in users:
        u.passwd='******'
    return dict(page=p,users=users)   

_RE_EMAIL=re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_SHA1=re.compile(r'^[0-9a-f]{40}$')

#用户注册API，用户在注册页面提交数据到这里，将用户数据存到数据库表users中    
@post('/api/users') #用户注册
async def api_register_user(*,email,name,passwd):
    if not name or not name.strip():    #strip()函数：用于移除字符串头尾指定的字符，默认为空格
        raise APIValueError('name')
    if not email or not _RE_EMAIL.match(email):
        raise APIValueError('email')
    if not passwd or not _RE_SHA1.match(passwd):
        raise APIValueError('passwd')
    users=await User.findAll('email=?',[email])
    if len(users)>0:
        raise APIError('注册失败','email','该邮箱已被注册。') 
    uid=next_id()
    sha1_passwd='%s:%s'%(uid,passwd) 
    #用户密码是客户端传递的经过SHA1计算后的40位Hash字符串     
    user=User(id=uid,name=name.strip(),email=email,passwd=hashlib.sha1(sha1_passwd.encode('utf-8')).hexdigest(),image='http://www.gravatar.com/avatar/%s?d=mm&s=120' %hashlib.md5(email.encode('utf-8')).hexdigest())
    await user.save()
    r=web.Response()
    r.set_cookie(COOKIE_NAME,user2cookie(user,86400),max_age=86400,httponly=True)
    user.passwd='******'
    r.content_type='application/json'
    r.body=json.dumps(user,ensure_ascii=False).encode('utf-8')
    return r      

#采用直接读取cookie的方式来验证用户登录，每次用户任意访问URL，都会对cookie进行验证
#登录成功后由服务器生成一个cookie发送给浏览器 
#通过单向算法SHA1实现防伪造cookie   
@post('/api/authenticate')  #登录验证
async def authenticate(*,email,passwd):
    if not email:
        raise APIValueError('email','无效的邮箱地址')
    if not passwd:
        raise APIValueError('passwd','密码错误（密码为本网站注册时的密码而非邮箱密码）')
    users=await User.findAll('email=?',[email])
    if len(users)==0:
        raise APIValueError('email','该邮箱未注册')
    user=users[0]
    #验证密码
    sha1=hashlib.sha1()
    sha1.update(user.id.encode('utf-8'))    #update()将两个字典合并操作，存在相同的键就覆盖
    sha1.update(b':')
    sha1.update(passwd.encode('utf-8')) 
    if user.passwd!=sha1.hexdigest():   #密码不匹配
        raise APIValueError('passwd','密码不匹配（密码为本网站注册时的密码而非邮箱密码）')
    r=web.Response()
    r.set_cookie(COOKIE_NAME,user2cookie(user,86400),max_age=86400,httponly=True)
    user.passwd='******'
    r.content_type='application/json'
    r.body=json.dumps(user,ensure_ascii=False).encode('utf-8')
    return r
    
#计算生成加密cookie，发送给服务器
def user2cookie(user,max_age):
    expires=str(int(time.time()+max_age))   #过期时间
    s='%s-%s-%s-%s'%(user.id,user.passwd,expires,_COOKIE_KEY)
    L=[user.id,expires,hashlib.sha1(s.encode('utf-8')).hexdigest()]#浏览器发送cookie给服务器的信息：包括用户id、过期时间和SHA1值
    return '-'.join(L)  
    
#对每个URL处理函数，解析cookie    
async def auth_factory(app,handler):
    async def auth(request):
        logging.info('check user:%s %s'%(request.method,request.path))
        request.__user__=None
        cookie_str=request.cookie.get(COOKIE_NAME)
        if cookie_str:
            user=await cookie2user(cookie_str)
            if user:
                logging.info('set current user:%s'%user.email)
                request.__user__=user
        return await handler(request)
    return auth

#解密cookie    
async def cookie2user(cookie_str):
    if not cookie_str:
        return None
    try:
        L=cookie_str.split('-') #通过指定分隔符对字符串进行切片，并返回分割后的字符串列表list
        if len(L)!=3:
            return None
        uid,expires,sha1=L
        if int(expires)<time.time():
            return None
        user=await User.find(uid)
        if user is None:
            return None
        s='%s-%s-%s-%s'%(uid,user.passwd,expires,_COOKIE_KEY)
        if sha1!=hashlib.sha1(s.encode('utf-8')).hexdigest():
            logging.info('invalid sha1')
            return None
        user.passwd='******'
        return user
    except Exception as e:
        logging.exception(e)
        return None  

def check_admin(request):
    if request.__user__ is None or not request.__user__.admin:
        raise APIPermissionError()
        
@post('/api/blogs') #创建日志
async def api_create_blog(request,*,title,summary,content):
    check_admin(request)
    if not title or not title.strip():
        raise APIValueError('title','标题不能为空。')
    if not summary or not summary.strip():
        raise APIValueError('summary','摘要不能为空。')
    if not content or not content.strip():
        raise APIValueError('content','内容不能为空。')
    blog=Blog(user_id=request.__user__.id,user_name=request.__user__.name,user_image=request.__user__.image,title=title.strip(),summary=summary.strip(),content=content.strip())
    await blog.save()
    return blog

@get('/api/blogs/{id}') #日志详情页
async def api_get_blog(*,id):
    blog=await Blog.find(id)
    return blog

@get('/api/blogs')  #获取日志列表
async def api_blogs(*,page='1'):
    page_index=get_page_index(page)
    num=await Blog.findNumber('count(id)')
    p=Page(num,page_index)
    if num==0:
        return dict(page=p,blogs=())
    blogs=await Blog.findAll(orderBy='created_at desc',limit=(p.offset,p.limit))
    return dict(page=p,blogs=blogs)      
               
@post('/api/blogs/{id}') #修改日志
async def api_update_blog(id,request,*,title,summary,content):
    check_admin(request)
    blog=await Blog.find(id)
    if not title or not title.strip():
        raise APIValueError('title','标题不能为空')
    if not summary or not summary.strip():
        raise APIValueError('summary','摘要不能为空')
    if not content or not content.strip():
        raise APIValueError('content','正文不能为空')
    blog.title=title.strip()
    blog.summary=summary.strip()
    blog.content=content.strip()
    await blog.update()
    return blog                

@post('/api/blogs/{id}/delete')
async def api_delete_blog(request,*,id):
    check_admin(request)
    blog=await Blog.find(id)
    await blog.remove()
    return dict(id=id)
    
@post('/api/blogs/{id}/comments')   #创建评论
async def api_create_comment(id,request,*,content):
    user=request.__user__
    if user is None:
        raise APIPermissionError('需要登录才能评论哦')
    if not content or not content.strip():
        raise APIValueError('content')        
    blog=await Blog.find(id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')      
    comment=Comment(blog_id=blog.id,user_id=user.id,user_name=user.name,user_image=user.image,content=content.strip()) 
    await comment.save()
    return comment
    
@get('/api/comments')
async def api_comments(*,page='1'):
    page_index=get_page_index(page)
    num=await Comment.findNumber('count(id)')
    p=Page(num,page_index)
    if num==0:
        return dict(page=p,comments=())    
    comments=await Comment.findAll(orderBy='created_at desc',limit=(p.offset,p.limit))
    return dict(page=p,comments=comments)                                              

@post('/api/comments/{id}/delete')
async def api_delete_comments(id,request):
    check_admin(request)
    c=await Comment.find(id)
    if c is None:
        raise APIResourceNotFoundError('Comment')
    await c.remove()
    return dict(id=id)                

#管理页面       
@get('/manage/')
def manage():
    return 'redirect:/manange/comments'
                
@get('/manage/blogs/create')
def manage_create_blog():
    return{
        '__template__':'manage_blog_edit.html',
        'id':'',
        'action':'/api/blogs'
    }  
 
def get_page_index(page_str):
    p=1
    try:
        p=int(page_str)
    except ValueError as e:
        pass
    if p<1:
        p=1
    return p                        
    
@get('/manage/blogs')
def manage_blogs(*,page='1'):
    return{
        '__template__':'manage_blogs.html',
        'page_index':get_page_index(page)
    }
    
@get('/manage/comments')
def manage_comments(*,page='1'):
    return{
        '__template__':'manage_comments.html',
        'page_index':get_page_index(page)
    }                                                                                                        
                                         
@get('/manage/blogs/edit')
def manage_edit_blog(*,id):
    return{
        '__template__':'manage_blog_edit.html',
        'id':id,
        'action':'/api/blogs/%s' %id
    }                               
    
@get('/manage/users')
def manage_users(*,page='1'):
    return{
        '__template__':'manage_users.html',
        'page_index':get_page_index(page)
    }                                                                                                   
