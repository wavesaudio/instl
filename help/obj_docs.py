import inspect

import pybatch

docs_dict = dict()


for name, obj in inspect.getmembers(pybatch, lambda member: inspect.isclass(member) and member.__module__.startswith(pybatch.__name__)):
    if inspect.isclass(obj):
        if obj.__doc__:
            sig = str(inspect.signature(obj.__init__)).replace('self, ', '').replace(' -> None', '').replace(', **kwargs', '')
            title = f"{obj.__name__}{sig}"
            doc_for_class = obj.__doc__.split("\n")
            doc_list = filter(None, (dfc.strip() for dfc in doc_for_class))
            docs_dict[title] = doc_list

for title, docs in docs_dict.items():
    print(f"""{title}:""")
    for doc in docs:
        print(f"""    {doc}""")
    print('---')


