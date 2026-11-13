cmake_minimum_required(VERSION 3.16.3)

project(INBRAINPlanner)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/Vive1Amour/inbrain-planner")
set(EXTENSION_CATEGORY "Neurosurgery")
set(EXTENSION_CONTRIBUTORS "Zelong Gan")
set(EXTENSION_DESCRIPTION "Pre-operative planning of cortical electrode-array placement to verify the glioblastoma resection boundary segment by segment: boundary segmentation near eloquent tracts, contact zoning by MRI, vein and conformity constraints, awake-time and cost comparison with conventional strips. Research use only.")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/Vive1Amour/inbrain-planner/main/INBRAINPlanner.png")
set(EXTENSION_STATUS "Beta")
set(EXTENSION_SCREENSHOTURLS "https://raw.githubusercontent.com/Vive1Amour/inbrain-planner/main/resources/imgs/UI_screenshot.png")
set(EXTENSION_DEPENDS "SlicerDMRI SlicerElastix")

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(INBRAINPlanner)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
