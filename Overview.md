# Key Features

## [ 1 ] Saving and Loading Python Objects

> allows saving and loading from files on disk and on buffers using `<type>` as either `json` or `pickle` 
* for files on disk
```python
    # save a file
    _ = known.basic.Kio.save_file(object, path, <type>)

    # load a file
    object = known.basic.Kio.load_file(path, <type>)


    # eg: save and load a json file
    my_object = dict(name="python", version=3.11)
    _ = known.basic.Kio.save_file(my_object, "./my_dict.json", "json")
    del my_object
    my_object = known.basic.Kio.load_file("./my_dict.json", "json")

    # eg: save and load a pickle file
    import numpy as np
    my_object = np.arange(100)
    _ = known.basic.Kio.save_file(my_object, "./my_array.pickle", "pickle")
    del my_object
    my_object = known.basic.Kio.load_file("./my_array.pickle", "pickle")

```
* for `io.BytesIO` buffers

```python
    # save a buffer
    buffer = known.basic.Kio.save_buffer(object, <type>)

    # load a buffer
    object = known.basic.Kio.load_buffer(buffer, <type>)


    # eg: save and load a json buffer
    my_object = dict(name="python", version=3.11)
    my_buffer = known.basic.Kio.save_buffer(my_object, "json")
    del my_object
    my_object = known.basic.Kio.load_buffer(my_buffer, "json") 
    # NOTE this buffer can be loaded multiple times before deleting
    # remeber to seek(0) before reading everytime
    del my_buffer

    # eg: save and load a pickle buffer
    import numpy as np
    my_object = np.arange(100)
    my_buffer = known.basic.Kio.save_buffer(my_object, "pickle")
    del my_object
    my_object = known.basic.Kio.load_buffer(my_buffer, "pickle")
    # NOTE this buffer can be loaded multiple times before deleting
    # remeber to seek(0) before reading everytime
    del my_buffer

```

## [ 2 ] Sending Mails

* Send automatic e-mails from inside your python code to any e-mail address
* It uses `smtplib` and a gmail account to send mails
*  It is adviced to use [app-password](https://myaccount.google.com/apppasswords)
* Supports sending files as attachements over e-mail 
* Inbuilt files and folders zipping functionality
* To send e-mails use the class `known.basic.Mailer` 
* Note: this is not an e-mail client, it can only send mails

```python
    # Sending a mail
    known.basic.Mailer.send(
        login=('username', 'password'),  # tuple/list of a gmail username and app-password
        subject = 'subject', # the subject line of e-mail
        rx = 'rx1@domain1.com,rx2@dmain2.org', # CSV list of `to` addresses
        cc = 'cc1@domain1.com,cc2@dmain2.org', # CSV list of `cc` addresses
        bcc = 'bcc1@domain1.com,bcc2@dmain2.org', # CSV list of `bcc` addresses
        content = 'Hello, I sent this Email', # Main body of the e-mail msg
        signature = 'Warm Regards,\nSender', # Signature at the end
        attached = [ # attachments
            ('',            ('file1.txt', 'file2.png'))
            ('files.zip',   ('file1.pdf', 'file2.log', 'folder1'))
        ] 
        verbose=True, # this will print a log on screen
        )
```
* the `attached` argument is like `list[ tuple(str, tuple(str...)) ]`
    * i.e., a list of two-tuples where, for each tuple
    * first element is the name of zip file
    * second element is a tuples of files 
* if name of zip file is not provided, all the files in the list will be attached individually
* if name of zip file is provided, then all files in the list will be zipped into one zip-file before attaching

## [ 3 ] AMQP Broker

* Implements a RabbitMQ Queue based broker using AMQP protocol
* Requires a broker running at the `host` address

```bash

python -m known.broker --user=user.py --host=172.17.0.2 --queue=hello

```

## [ 4 ] API Server

* Implements a python+Flask based API that allow applications to send and recieve data as json and bytes (buffers)
* Requires definig handlers in `user.py`

```bash

python -m known.api --user=user.py --object=UserModule --callable=1

```

## [ 5 ] Topics Server

* Implements a python+Flask based web-app that allow users to share files on a local network
* Requires definig configuration and users `configs.py` and `__login__.csv`

```bash

python -m known.topics --dir=path/to/base/folder

```
