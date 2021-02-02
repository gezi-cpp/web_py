#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#‘Model实例，即对应各种表的各个类’

__author__='by花'

from Instance_Model import User,Blog,Comment
import asyncio
import ORM

loop=asyncio.get_event_loop()   
async def test():
    await ORM.create_pool(user='www-data',password='www-data',db='web_python',loop=loop)#创建数据库连接
#    await ORM.create_pool(loop=loop)
    """
    user1=User(id=123,name='Michael') 
    await user1.save() #user.save()没有任何效果，仅仅是创建了一个协程并没有执行。必须加上await，才真正进行了INSERT操作
    
    user2=User(id=765,name='bb')
    await user2.save() 
  
    requ=await User.find('666') #@classmethod的作用，可以不使用类实例调用类函数
    print(requ)
    print ('text:',requ.__select__)
    """
    user2=User(name='Test',email='test@example.com',passwd='1234567890',image='about:blank')
    await user2.save() 
    print(await User.findAll())
    print(await User.findNumber())
    
loop.run_until_complete(test())
