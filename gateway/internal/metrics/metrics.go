// Package metrics is a small Prometheus text-format registry: counters and histograms with labels.
package metrics

import (
	"fmt"
	"io"
	"math"
	"sort"
	"strings"
	"sync"
)

type Registry struct {
	mu       sync.Mutex
	counters map[string]*counter
	hists    map[string]*histogram
}

type counter struct {
	help   string
	values map[string]float64
}

type histogram struct {
	help    string
	buckets []float64
	series  map[string]*hseries
}

type hseries struct {
	counts []uint64
	sum    float64
	n      uint64
}

func New() *Registry {
	return &Registry{counters: map[string]*counter{}, hists: map[string]*histogram{}}
}

func labelKey(labels []string) string {
	if len(labels)%2 != 0 {
		panic("labels must be key/value pairs")
	}
	var parts []string
	for i := 0; i < len(labels); i += 2 {
		v := strings.NewReplacer(`\`, `\\`, `"`, `\"`, "\n", `\n`).Replace(labels[i+1])
		parts = append(parts, fmt.Sprintf(`%s="%s"`, labels[i], v))
	}
	return strings.Join(parts, ",")
}

func (r *Registry) Counter(name, help string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.counters[name] = &counter{help: help, values: map[string]float64{}}
}

func (r *Registry) Histogram(name, help string, buckets []float64) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.hists[name] = &histogram{help: help, buckets: buckets, series: map[string]*hseries{}}
}

func (r *Registry) Add(name string, v float64, labels ...string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	c, ok := r.counters[name]
	if !ok {
		panic("unknown counter " + name)
	}
	c.values[labelKey(labels)] += v
}

func (r *Registry) Observe(name string, v float64, labels ...string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	h, ok := r.hists[name]
	if !ok {
		panic("unknown histogram " + name)
	}
	k := labelKey(labels)
	s, ok := h.series[k]
	if !ok {
		s = &hseries{counts: make([]uint64, len(h.buckets))}
		h.series[k] = s
	}
	for i, b := range h.buckets {
		if v <= b {
			s.counts[i]++
		}
	}
	s.sum += v
	s.n++
}

// Get returns a counter's value (tests).
func (r *Registry) Get(name string, labels ...string) float64 {
	r.mu.Lock()
	defer r.mu.Unlock()
	if c, ok := r.counters[name]; ok {
		return c.values[labelKey(labels)]
	}
	return math.NaN()
}

func (r *Registry) Write(w io.Writer) {
	r.mu.Lock()
	defer r.mu.Unlock()
	var names []string
	for n := range r.counters {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		c := r.counters[n]
		fmt.Fprintf(w, "# HELP %s %s\n# TYPE %s counter\n", n, c.help, n)
		keys := sortedKeys(c.values)
		for _, k := range keys {
			fmt.Fprintf(w, "%s{%s} %g\n", n, k, c.values[k])
		}
	}
	names = names[:0]
	for n := range r.hists {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		h := r.hists[n]
		fmt.Fprintf(w, "# HELP %s %s\n# TYPE %s histogram\n", n, h.help, n)
		var keys []string
		for k := range h.series {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			s := h.series[k]
			sep := ""
			if k != "" {
				sep = ","
			}
			for i, b := range h.buckets {
				fmt.Fprintf(w, "%s_bucket{%s%sle=\"%g\"} %d\n", n, k, sep, b, s.counts[i])
			}
			fmt.Fprintf(w, "%s_bucket{%s%sle=\"+Inf\"} %d\n%s_sum{%s} %g\n%s_count{%s} %d\n", n, k, sep, s.n, n, k, s.sum, n, k, s.n)
		}
	}
}

func sortedKeys(m map[string]float64) []string {
	var ks []string
	for k := range m {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	return ks
}
