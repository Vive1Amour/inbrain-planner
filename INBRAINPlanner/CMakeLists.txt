#-----------------------------------------------------------------------------
set(MODULE_NAME INBRAINPlanner)

#-----------------------------------------------------------------------------
set(MODULE_PYTHON_SCRIPTS
  ${MODULE_NAME}.py
  ${MODULE_NAME}Lib/__init__.py
  ${MODULE_NAME}Lib/i18n.py
  ${MODULE_NAME}Lib/config.py
  ${MODULE_NAME}Lib/logic.py
  )

# Runtime files are installed with the module (Slicer extension layout):
#   Resources/Icons     module icon
#   Resources/Pipeline  planning and preprocessing scripts run inside Slicer
#   Resources/Settings  device library, display styles, eloquence priors
# Resources/ExtLibs (brain-atlas template, ~32 MB) is not in the repository;
# the module asks for its folder when the atlas step is used.
file(GLOB _pipeline RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} Resources/Pipeline/*.py Resources/Pipeline/*.sh)
file(GLOB _settings RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} Resources/Settings/*.json)
set(MODULE_PYTHON_RESOURCES
  Resources/Icons/${MODULE_NAME}.png
  ${_pipeline}
  ${_settings}
  )

#-----------------------------------------------------------------------------
slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_PYTHON_SCRIPTS}
  RESOURCES ${MODULE_PYTHON_RESOURCES}
  WITH_GENERIC_TESTS
  )

#-----------------------------------------------------------------------------
# Self-test (INBRAINPlannerTest): unit checks always run; the planning regression
# runs only when a UCSF-PDGM case is found (env INBRAIN_TEST_CASE), otherwise it is skipped.
if(BUILD_TESTING)
  slicer_add_python_unittest(SCRIPT ${MODULE_NAME}.py)
endif()
