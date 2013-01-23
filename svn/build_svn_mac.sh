#!/bin/bash

set -e

sdks_folder="/p4client/ProAudio/SDKs"

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

apr_source_folder="$sdks_folder/apr/apr-1.4.6"
if [ ! -d "$apr_source_folder" ]
then
    echo "Could not find apr source folder at $apr_source_folder"
    exit 1
fi

apr_utils_source_folder="$sdks_folder/apr/apr-util-1.5.1"
if [ ! -d "$apr_utils_source_folder" ]
then
    echo "Could not find apr-util source folder at $apr_utils_source_folder"
    exit 1
fi

neon_source_folder="$sdks_folder/neon/neon-0.29.6"
if [ ! -d "$neon_source_folder" ]
then
    echo "Could not find neon source folder at $neon_source_folder"
    exit 1
fi

sqlite_amalgamation_folder="$sdks_folder/sqlite/3071502/sqlite-amalgamation"
if [ ! -d "$sqlite_amalgamation_folder" ]
then
    echo "Could not find sqlite amalgamation folder at $sqlite_amalgamation_folder"
    exit 1
fi


intermediate_build_folder="$sdks_folder/../wsvn/build"
mkdir -p "$intermediate_build_folder"
if [ ! -d "$intermediate_build_folder" ]
then
    echo "Could not find intermediate build folder at $intermediate_build_folder"
    exit 1
fi

final_product_folder="$sdks_folder/../wsvn/products"
mkdir -p "$final_product_folder"
if [ ! -d "$final_product_folder" ]
then
    echo "Could not find final product folder at $final_product_folder"
    exit 1
fi

if [ "$#" > 0 ]
then
    if [ "$1" == "clean" ]
    then
        echo "clean, clean, clean"
        cd "$apr_source_folder"
        make clean
        cd "$apr_utils_source_folder"
        make clean
        cd "$neon_source_folder"
        make clean
        cd "$subversion_source_folder"
        make clean
        cd "$intermediate_build_folder"
        find . -type f -print0 | xargs -0 rm -vfr
        cd "$final_product_folder"
        find . -type f -print0 | xargs -0 rm -vfr
        exit 0
    fi
fi

export CFLAGS="-DAPR_DECLARE_STATIC -arch i386"

cd "$apr_source_folder"
mkdir -p "$intermediate_build_folder/apr"
./configure --prefix="$intermediate_build_folder/apr" --enable-shared=no --enable-static=yes > "$intermediate_build_folder/apr/config.out"
make
make install

cd "$apr_utils_source_folder"
mkdir -p "$intermediate_build_folder/apr-util"
./configure --prefix="$intermediate_build_folder/apr-util" --with-apr="$intermediate_build_folder/apr/bin/apr-1-config"   > "$intermediate_build_folder/apr-util/config.out"
make
make install

cd "$neon_source_folder"
mkdir -p "$intermediate_build_folder/neon"
./configure --prefix="$intermediate_build_folder/neon" --with-ssl=openssl > "$intermediate_build_folder/neon/config.out"
make
make install


cd "$subversion_source_folder"
mkdir -p "$intermediate_build_folder/svn"
./configure --prefix="$intermediate_build_folder/svn" --enable-all-static --with-ssl --without-berkeley-db --without-apache-libexecdir --with-apr="$intermediate_build_folder/apr/bin/apr-1-config" --with-apr-util="$intermediate_build_folder/apr-util/bin/apu-1-config" --with-neon="$intermediate_build_folder/neon" --with-sqlite="$sqlite_amalgamation_folder/sqlite3.c"   > "$intermediate_build_folder/svn/config.out"
make
make install
