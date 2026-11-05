CXX ?= c++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wpedantic
PYTHON ?= python3
BUILD := build/release

.PHONY: all test check-size clean
all: $(BUILD)/brain

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/brain: src/brain.cpp | $(BUILD)
	$(CXX) $(CXXFLAGS) $< -o $@

$(BUILD)/test_engine: tests/test_engine.cpp src/brain.cpp | $(BUILD)
	$(CXX) $(CXXFLAGS) $< -o $@

$(BUILD)/test_tt: tests/test_search_v3_tt.cpp src/brain.cpp | $(BUILD)
	$(CXX) $(CXXFLAGS) $< -o $@

$(BUILD)/test_vct: tests/test_vct_v5.cpp src/brain.cpp | $(BUILD)
	$(CXX) $(CXXFLAGS) $< -o $@

$(BUILD)/probe_stateful: training/probe_stateful.cpp src/brain.cpp | $(BUILD)
	$(CXX) $(CXXFLAGS) $< -o $@

check-size: all
	$(PYTHON) scripts/check_release.py src/brain.cpp $(BUILD)/brain

test: all $(BUILD)/test_engine $(BUILD)/test_tt $(BUILD)/test_vct $(BUILD)/probe_stateful check-size
	$(BUILD)/test_engine
	$(BUILD)/test_tt
	$(BUILD)/test_vct
	$(PYTHON) -m unittest discover -s tests -p test_export_games.py
	$(PYTHON) tests/test_stateful_probe.py --probe $(BUILD)/probe_stateful --protocol $(BUILD)/brain --output $(BUILD)/stateful_validation.json

clean:
	rm -rf $(BUILD)
