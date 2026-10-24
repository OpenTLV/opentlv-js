# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OpenTLV
include(FetchContent)
set(_lock "${CMAKE_CURRENT_LIST_DIR}/core-source.json")
set(_features "${CMAKE_CURRENT_LIST_DIR}/core-features.json")
set(_verifier "${PROJECT_SOURCE_DIR}/scripts/core_dependency.py")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${_lock}" "${_features}" "${_verifier}")
file(READ "${_lock}" _lock_json)
string(JSON _repository GET "${_lock_json}" repository)
string(JSON _commit GET "${_lock_json}" commit)
string(LENGTH "${_commit}" _commit_length)
if(NOT _commit_length EQUAL 40 OR NOT _commit MATCHES "^[0-9a-f]+$")
    message(FATAL_ERROR "Core source lock must contain an exact Git commit")
endif()

if(FETCHCONTENT_SOURCE_DIR_OPENTLV_CORE)
    file(REAL_PATH "${FETCHCONTENT_SOURCE_DIR_OPENTLV_CORE}" OPENTLV_JS_CORE_SOURCE)
    set(_core_mode local-development)
else()
    # Populate only: verify the source before executing its CMake code.
    set(FETCHCONTENT_TRY_FIND_PACKAGE_MODE NEVER)
    FetchContent_Declare(opentlv_core
        GIT_REPOSITORY "${_repository}"
        GIT_TAG "${_commit}"
        GIT_CONFIG core.autocrlf=false core.abbrev=9
        SOURCE_SUBDIR .opentlv-js-populate-only)
    FetchContent_MakeAvailable(opentlv_core)
    set(OPENTLV_JS_CORE_SOURCE "${opentlv_core_SOURCE_DIR}")
    set(_core_mode pinned-source)
endif()
set(_receipt "${PROJECT_BINARY_DIR}/core-selection.json")
set(_verify_args --source "${OPENTLV_JS_CORE_SOURCE}" --mode "${_core_mode}")
execute_process(COMMAND "${Python3_EXECUTABLE}" -B "${_verifier}"
    ${_verify_args} --output "${_receipt}" RESULT_VARIABLE _verify_result)
if(NOT _verify_result EQUAL 0)
    message(FATAL_ERROR "Core source verification failed; no dependency fallback is allowed")
endif()

file(READ "${_features}" _features_json)
string(JSON _count LENGTH "${_features_json}")
math(EXPR _last "${_count} - 1")
foreach(_index RANGE ${_last})
    string(JSON _feature GET "${_features_json}" ${_index})
    set(${_feature} ON CACHE INTERNAL "Required by the baseline JS facade" FORCE)
    set(${_feature} ON)
endforeach()
foreach(_option IN ITEMS OPENTLV_BUILD_SHARED_LIBS OPENTLV_BUILD_CXX
        OPENTLV_BUILD_WASM OPENTLV_BUILD_TESTS OPENTLV_BUILD_EXAMPLES
        OPENTLV_BUILD_DOCS OPENTLV_BUILD_BENCHMARKS OPENTLV_BUILD_FUZZING
        OPENTLV_BUILD_LUA OPENTLV_BUILD_PYTHON OPENTLV_BUILD_MEMCHECK)
    set(${_option} OFF CACHE INTERNAL "Build only the static Core dependency" FORCE)
    set(${_option} OFF)
endforeach()
set(OPENTLV_WARNINGS_AS_ERRORS ON CACHE BOOL "Treat compiler warnings as errors")
add_subdirectory("${OPENTLV_JS_CORE_SOURCE}" "${PROJECT_BINARY_DIR}/core" EXCLUDE_FROM_ALL)
if(NOT TARGET OpenTLV::tlv)
    message(FATAL_ERROR "Selected Core must provide OpenTLV::tlv")
endif()
# Include the selected Core compiler policy in this directory's scope as well.
include("${OPENTLV_JS_CORE_SOURCE}/cmake/compiler.cmake")
add_custom_target(opentlv-js-check-core
    COMMAND "${Python3_EXECUTABLE}" -B "${_verifier}" ${_verify_args} --check "${_receipt}"
    COMMENT "Verify that selected Core inputs still match configure-time provenance"
    VERBATIM)
get_target_property(_core_target OpenTLV::tlv ALIASED_TARGET)
get_target_property(_core_type ${_core_target} TYPE)
if(NOT _core_type STREQUAL "STATIC_LIBRARY")
    message(FATAL_ERROR "The WASM module requires a static Core library")
endif()
file(READ "${PROJECT_BINARY_DIR}/core/generated/include/tlv/config.h" _config)
foreach(_index RANGE ${_last})
    string(JSON _feature GET "${_features_json}" ${_index})
    if(NOT _config MATCHES "#define ${_feature} 1[\r\n]")
        message(FATAL_ERROR "Selected Core does not provide required feature ${_feature}")
    endif()
endforeach()
add_dependencies(${_core_target} opentlv-js-check-core)
