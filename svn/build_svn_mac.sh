#!/bin/bash

set -e

sdks_folder="/Volumes/p4client/SDKs"

if [ ! -d "$sdks_folder" ]
then 
    echo "Could not find SDks folder at $sdks_folder"
    exit 1
fi

subversion_source_folder="$sdks_folder/svn/subversion-1.7.8"
if [ ! -d "$subversion_source_folder" ]
then 
    echo "Could not find subversion source folder at $subversion_source_folder"
    exit 1
fi

neon_source_folder="/$sdks_folder/neon/neon-0.29.6"
if [ ! -d "$neon_source_folder" ]
then 
    echo "Could not find neon source folder at $neon_source_folder"
    exit 1
fi

sqlite_amalgamation_folder="/$sdks_folder/sqlite/3071502/sqlite-amalgamation"
if [ ! -d "$sqlite_amalgamation_folder" ]
then 
    echo "Could not find sqlite amalgamation folder at $sqlite_amalgamation_folder"
    exit 1
fi

intermediate_build_folder="$sdks_folder/../build_wsvn"
mkdir -p "$intermediate_build_folder"
if [ ! -d "$intermediate_build_folder" ]
then 
    echo "Could not find intermediate build folder at $intermediate_build_folder"
    exit 1
fi

final_product_folder="$sdks_folder/../wsvn"
mkdir -p "$final_product_folder"
if [ ! -d "$final_product_folder" ]
then 
    echo "Could not find final product folder at $final_product_folder"
    exit 1
fi

cd "$neon_source_folder"
mkdir -p "$intermediate_build_folder/neon"
./configure --prefix="$intermediate_build_folder/neon" --with-ssl=openssl > "$intermediate_build_folder/neon/config.out"
make
make install


cd "$subversion_source_folder"
mkdir -p "$intermediate_build_folder/svn"
./configure --prefix="$final_product_folder/svn" --enable-all-static --with-ssl --with-neon="$intermediate_build_folder/neon" --with-sqlite="$sqlite_amalgamation_folder/sqlite3.c"  --with-apache-libexecdir="$intermediate_build_folder/apache" > "$intermediate_build_folder/svn/config.out"

make
make install
