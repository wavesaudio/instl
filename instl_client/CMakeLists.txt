cmake_minimum_required(VERSION 3.16)
project(instl_client LANGUAGES CXX)

add_executable(instl-client instl_client.cpp)
target_compile_features(instl-client PRIVATE cxx_std_20)

find_path(INSTL_UTILITIES_INCLUDE
    NAMES fstring/fstring.h
    HINTS "${CMAKE_CURRENT_SOURCE_DIR}/../../../Utilities")
if(NOT INSTL_UTILITIES_INCLUDE)
    message(FATAL_ERROR "fstring/fstring.h was not found")
endif()

find_path(INSTL_JSON_INCLUDE
    NAMES jsonland/json_node.h
    HINTS "${CMAKE_CURRENT_SOURCE_DIR}/../../../Utilities/JSON")
if(NOT INSTL_JSON_INCLUDE)
    message(FATAL_ERROR "jsonland/json_node.h was not found")
endif()

# Build jsonland without importing repository-level CMake setup.
target_sources(instl-client PRIVATE "${INSTL_JSON_INCLUDE}/jsonland/json_node.cpp")
target_include_directories(instl-client PRIVATE
    "${INSTL_UTILITIES_INCLUDE}"
    "${INSTL_JSON_INCLUDE}")

if(APPLE)
    target_compile_definitions(instl-client PRIVATE __MACOS__)
elseif(WIN32)
    target_compile_definitions(instl-client PRIVATE _WINDOWS _WINDOWS_ WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(instl-client PRIVATE ws2_32)
endif()

if(MSVC)
    target_compile_options(instl-client PRIVATE /W4 /permissive-)
else()
    target_compile_options(instl-client PRIVATE -Wall -Wextra -Wpedantic)
endif()
