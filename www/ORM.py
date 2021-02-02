#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#‘ORM--对象关系映射：把关系数据库的一行映射为一个对象，也就是一个类对应一个表’

__author__='by花'

import aiomysql
import logging; logging.basicConfig(level=logging.INFO)
import asyncio,os,json,time
#from boto.compat import StandardError
#from socks import log

def log(sql):
    logging.info('SQL:%s' %sql) #打印sql
    
#创建连接池__pool，每个HTTP请求都可以从连接池获取数据库连接
async def create_pool(loop,**kw):
    logging.info('create database connection pool...')
    global __pool
    __pool=await aiomysql.create_pool(
        host=kw.get('host','localhost'),    #主机号
        port=kw.get('port',3306),           #端口号
        user=kw['user'],                    #用户名
        password=kw['password'],
        db=kw['db'],                        #数据库
        charset=kw.get('charset','utf8'),
        autocommit=kw.get('autocommit',True),#自动提交
        maxsize=kw.get('maxsize',10),       #最大连接数量
        minsize=kw.get('minsize',1),        #最小连接数量
        loop=loop
    )
    
#SELECT查询语句。三个参数分别为：SQL语句、SQL参数、查询数量
async def select(sql,args,size=None):
    log(sql)
    global __pool
    #从连接池pool中取连接conn
    with (await __pool) as conn:
        cur=await conn.cursor(aiomysql.DictCursor)#创建一个Cursor，参数为？？？
        #执行一条SQL语句
        await cur.execute(sql.replace('?','%s'),args or ())#MySQL占位符%s替换SQL语句占位符？
        if size:
            rs=await cur.fetchmany(size)#传入size参，获得指定数量记录
        else:
            rs=await cur.fetchall()#不传size参，获得所有记录
        await cur.close()
        logging.info('rows returned:%s' %len(rs))
        return rs
        
#execute操作语句        
async def execute(sql,args):
    log(sql)
    global __pool
    async with __pool.get() as conn:
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                #cur=await conn.cursor()
                await cur.execute(sql.replace('?','%s'),args)
                affected=cur.rowcount
                await cur.close()
        except BaseException as e:
            raise
        return affected            
#Field类：用于完成数据库表数据到类属性的映射。负责保存数据库表的字段名、字段类型和主key    
class Field(object):
    #Field基类属性：name、类型、主key、默认
    def __init__(self,name,ddl,primary_key,default):
        self.name=name
        self.column_type=ddl
        self.primary_key=primary_key
        self.default=default
        
    def __str__(self):
        return '<%s,%s:%s>'%(self.__class__.__name__,self.column_type,self.name)

#Field子类：构造关系数据库表属性        
#字符串Field子类         
class StringField(Field):   #varchar可变长度   
    def __init__(self,name=None,primary_key=False,default=None,ddl='varchar(100)'):
        super().__init__(name,ddl,primary_key,default)
#整型Field子类
class IntegerField(Field):
    def __init__(self,name=None,primary_key=False,default=0):
        super().__init__(name,'bigint',primary_key,default)    
#布尔Field子类
class BooleanField(Field):
    def __init__(self,name=None,default=False):
        super().__init__(name,'boolean',False,default)    
#浮点型Field子类
class FloatField(Field):
    def __init__(self,name=None,primary_key=False,default=0.0):
        super().__init__(name,'real',primary_key,default)
#文本型Field子类            
class TextField(Field):
    def __init__(self,name=None,default=None):
        super().__init__(name,'text',False,default)         
        
def create_args_string(num):
    L=[]
    for n in range(num):
        L.append('?')
    return ','.join(L)  #join为用指定的字符连接生成一个新字符串                                                
        
class ModelMetaclass(type):#元类
    def __new__(cls,name,bases,attrs):#四个参数依次是：当前准备创建的类的对象、类的名字、类继承的父类集合和类的方法集合
        if name=='Model':#排除对Model类的修改，对Model类派生出来的子类进行修改
            return type.__new__(cls,name,bases,attrs)
        tableName=attrs.get('__table__',None) or name   #获取table名称，默认为类名
        logging.info('found model:%s(table:%s)'%(name,tableName))    
        #获取所有的Field属性和主键名
        mappings=dict()
        fields=[]
        primaryKey=None
        for k,v in attrs.items(): #Model子类实例化参数都传到了attrs中
            if isinstance(v,Field): #如果找到一个Field属性，就把它保存到__mappings__的dict中
                logging.info('found mapping:%s ==> %s' %(k,v)) 
                mappings[k]=v
                if v.primary_key:
                    if primaryKey:
                        raise RuntimeError('Duplicate primary key for field:%s' %k)
                    primaryKey=k
                else:
                    fields.append(k)
        if not primaryKey:
            raise RuntimeError('Primary key not found.')
        for k in mappings.keys():
            attrs.pop(k)  #从类属性中删除该Field属性，否则实例的属性会掩盖类的同名属性
        escape_fields=list(map(lambda f:'`%s`'%f,fields))
        attrs['__mappings__']=mappings      #保存属性和列的映射关系
        attrs['__table__']=tableName        #表名
        attrs['__primary_key__']=primaryKey #主键属性名
        attrs['__fields__']=fields          #除主键外的属性名,只存名字不存值
        #构造默认的SELECT，INSERT，UPDATE和DELETE语句：
        attrs['__select__']='select `%s`,%s from `%s`'%(primaryKey,','.join(escape_fields),tableName)
        attrs['__insert__']='insert into `%s`(%s,`%s`) values (%s)'%(tableName,','.join(escape_fields),primaryKey,create_args_string(len(escape_fields)+1))
        attrs['__update__']='update `%s` set %s where `%s`=?'%(tableName,','.join(map(lambda f:'`%s`=?'%(mappings.get(f).name or f),fields)),primaryKey)
        attrs['__delete__']='delete from `%s` where `%s`=?'%(tableName,primaryKey)
        return type.__new__(cls,name,bases,attrs)                        
                                                                                           
        
class Model(dict,metaclass=ModelMetaclass):
    
    def __init__(self,**kw):
        super(Model,self).__init__(**kw)
    #在没有找到属性的情况下会调用__getattr__    
    def __getattr__(self,key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" %key) 
                                   
    def __setattr__(self,key,value):
        self[key]=value
        
    def getValue(self,key):
        return getattr(self,key,None)
        
    def getValueOrDefault(self,key):
        value=getattr(self,key,None)
        if value is None:
            field=self.__mappings__[key]
            if field.default is not None:
                value=field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s:%s'%(key,str(value)))
                setattr(self,key,value)
        return value   
        
    async def save(self):
        args=list(map(self.getValueOrDefault,self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows=await execute(self.__insert__,args)
        if rows != 1:
            logging.warn('failed to insert record:affected rows:%s' %rows)
        else:
            logging.info('succeed to insert record:affected rows:%s' %rows)
            
    async def update(self): 
        args=list(map(self.getValue,self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows=await execute(self.__update__,args)
        if rows != 1:
            logging.warn('failed to update record:affected rows:%s' %rows)
        else:
            logging.info('succeed to update record:affected rows:%s' %rows) 
            
    async def remove(self): 
        args=[self.getValue(self.__primary_key__)]
        rows=await execute(self.__delete__,args)
        if rows != 1:
            logging.warn('failed to delete record:affected rows:%s' %rows)
        else:
            logging.info('succeed to delete record:affected rows:%s' %rows)                               
                                                
                
    #@classmethod表明该方法是类方法，类方法不需要实例化类就可以被类本身调用，第一个参数必须是cls，代表自身类
    #cls调用类方法时必须加括号，例如cls().function()                
    @classmethod
    async def find(cls,pk):   
        'find object by primary key.'
        rs=await select('%s where `%s`=?'%(cls.__select__,cls.__primary_key__),[pk],1)#传入select函数，该函数返回查询的记录
        if len(rs)==0:
            return None
        return cls(**rs[0])   
        
    @classmethod
    async def findAll(cls,where=None,args=None,**kw):
        'find object by where clause'
        sql=[cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args=[]
        orderBy=kw.get('orderBy',None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit=kw.get('limit',None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit,int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit,tuple) and len(limit)==2:
                sql.append('?,?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value:%s'%str(limit))
        rs=await select(' '.join(sql),args)
        return [cls(**r) for r in rs]                                                                        
                                      
    @classmethod
    async def findNumber(cls):
        'find number by table name.'
        number=await select('select count(*) from `%s`'%(cls.__table__),0)
        return cls(**number[0])['count(*)']              


            
