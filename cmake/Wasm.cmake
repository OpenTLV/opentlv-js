# Experimental WebAssembly module: the OpenTLV C core plus a small parsing
# boundary (native/opentlv_wasm.h), compiled by the standalone Emscripten build.
#
#   emcmake cmake -S . -B build-wasm -G Ninja -DCMAKE_BUILD_TYPE=Release
#   cmake --build build-wasm --target opentlv-wasm

add_executable(opentlv-wasm native/opentlv_wasm.c native/opentlv_wasm.h
    native/path_query.h native/query_schema.h)
target_link_libraries(opentlv-wasm PRIVATE OpenTLV::tlv)
target_include_directories(opentlv-wasm PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/native)
opentlv_configure_compiler(opentlv-wasm)

set(_wasm_output_dir "${CMAKE_CURRENT_BINARY_DIR}/dist")
set_target_properties(opentlv-wasm PROPERTIES
    OUTPUT_NAME opentlv-core
    SUFFIX ".js"
    RUNTIME_OUTPUT_DIRECTORY "${_wasm_output_dir}"
)
set_property(TARGET opentlv-wasm APPEND PROPERTY LINK_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/opentlv.mjs"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/query.mjs")

# Exported entry points come from EMSCRIPTEN_KEEPALIVE in opentlv_wasm.h. The
# module is an ES module exporting a createOpenTLV() factory; it has no main()
# and no file system, and its memory grows on demand.
target_link_options(opentlv-wasm PRIVATE
    --no-entry
    -sMODULARIZE=1
    -sEXPORT_ES6=1
    -sEXPORT_NAME=createOpenTLV
    -sENVIRONMENT=web,worker,node
    -sALLOW_MEMORY_GROWTH=1
    -sFILESYSTEM=0
    -sALLOW_TABLE_GROWTH=1
    "-sEXPORTED_RUNTIME_METHODS=['HEAPU8','UTF8ToString','stringToUTF8','lengthBytesUTF8','addFunction','removeFunction']"
)

# The JavaScript wrapper is the documented browser entry point; ship it next to
# the generated module and .wasm file.
add_custom_command(TARGET opentlv-wasm POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/src/opentlv.mjs" "${_wasm_output_dir}/opentlv.mjs"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/src/query.mjs" "${_wasm_output_dir}/query.mjs"
    VERBATIM
)

option(OPENTLV_BUILD_WASM_TESTS "Register the Node.js smoke test for the WebAssembly module" ON)
if(OPENTLV_BUILD_WASM_TESTS)
    find_program(OPENTLV_NODE_EXECUTABLE node)
    if(OPENTLV_NODE_EXECUTABLE)
        add_test(NAME Integration_wasm
            COMMAND ${OPENTLV_NODE_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/smoke.mjs" "${_wasm_output_dir}")
        set_tests_properties(Integration_wasm PROPERTIES LABELS "integration;wasm")

        # The "parse" use-case example shared with examples/tlv, examples/tlv++
        # and the opentlv-rust examples; there is no "write", "query" or
        # "validate" JS example yet, see examples/parse.mjs.
        add_test(NAME Integration_example_wasm_parse
            COMMAND ${OPENTLV_NODE_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/examples/parse.mjs" "${_wasm_output_dir}")
        set_tests_properties(Integration_example_wasm_parse PROPERTIES LABELS "integration;examples;wasm")
    else()
        message(STATUS "node not found; skipping the WebAssembly smoke test.")
    endif()
endif()

# BEGIN generic-fields #3
if(OPENTLV_BUILD_WASM_TESTS AND OPENTLV_NODE_EXECUTABLE)
    add_test(NAME Integration_wasm_fields
        COMMAND ${OPENTLV_NODE_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/format_fields.mjs" "${_wasm_output_dir}")
    add_test(NAME Integration_example_wasm_fields
        COMMAND ${OPENTLV_NODE_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/examples/fields.mjs" "${_wasm_output_dir}")
    set_tests_properties(Integration_wasm_fields Integration_example_wasm_fields
        PROPERTIES LABELS "integration;wasm")
endif()
# END generic-fields #3

# BEGIN streaming #4
target_sources(opentlv-wasm PRIVATE native/streaming.h)
if(OPENTLV_BUILD_WASM_TESTS AND OPENTLV_NODE_EXECUTABLE)
    add_test(NAME Integration_wasm_streaming
        COMMAND ${OPENTLV_NODE_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/streaming.mjs" "${_wasm_output_dir}")
    add_test(NAME Integration_example_wasm_streaming
        COMMAND ${OPENTLV_NODE_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/examples/streaming.mjs" "${_wasm_output_dir}")
    set_tests_properties(Integration_wasm_streaming Integration_example_wasm_streaming
        PROPERTIES LABELS "integration;wasm")
endif()
# END streaming #4

# BEGIN document-schema #5
set_property(TARGET opentlv-wasm APPEND PROPERTY LINK_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/opentlv.d.mts"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/query.d.mts")
add_custom_command(TARGET opentlv-wasm POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/src/opentlv.d.mts" "${_wasm_output_dir}/opentlv.d.mts"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/src/query.d.mts" "${_wasm_output_dir}/query.d.mts"
    VERBATIM)
target_sources(opentlv-wasm PRIVATE native/document_schema.h)
if(OPENTLV_BUILD_WASM_TESTS AND OPENTLV_NODE_EXECUTABLE)
    add_test(NAME Integration_wasm_document_schema
        COMMAND ${OPENTLV_NODE_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/document_schema.mjs" "${_wasm_output_dir}")
    add_test(NAME Integration_example_wasm_document_schema
        COMMAND ${OPENTLV_NODE_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/examples/document_schema.mjs" "${_wasm_output_dir}")
    set_tests_properties(Integration_wasm_document_schema Integration_example_wasm_document_schema
        PROPERTIES LABELS "integration;wasm")
endif()
# END document-schema #5
