# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
cmake_minimum_required(VERSION 3.24)
project(OpenTLVJS LANGUAGES C)

if(NOT EMSCRIPTEN)
    message(FATAL_ERROR "OpenTLV JS requires Emscripten 4.0.10; configure with emcmake cmake")
endif()
execute_process(COMMAND "${CMAKE_C_COMPILER}" --version
    OUTPUT_VARIABLE _emcc_version RESULT_VARIABLE _emcc_result)
if(NOT _emcc_result EQUAL 0 OR NOT _emcc_version MATCHES "emcc \\([^\n]*\\) 4\\.0\\.10([ \n]|$)")
    message(FATAL_ERROR "The migration build requires Emscripten 4.0.10")
endif()
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()
find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
option(OPENTLV_BUILD_WASM_TESTS "Register Node smoke and parse example tests" ON)
if(OPENTLV_BUILD_WASM_TESTS)
    find_program(OPENTLV_NODE_EXECUTABLE node REQUIRED)
    execute_process(COMMAND "${OPENTLV_NODE_EXECUTABLE}" --version
        OUTPUT_VARIABLE _node_version RESULT_VARIABLE _node_result)
    if(NOT _node_result EQUAL 0 OR NOT _node_version MATCHES "^v22\\.")
        message(FATAL_ERROR "The migration tests require Node 22")
    endif()
    enable_testing()
endif()
include(cmake/Core.cmake)
include(cmake/Wasm.cmake)
