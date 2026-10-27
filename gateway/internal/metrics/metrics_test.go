package metrics

import (
	"strings"
	"testing"
)

func TestExposition(t *testing.T) {
	r := New()
	r.Counter("c_total", "help")
	r.Histogram("h_seconds", "help", []float64{1, 2})
	r.Add("c_total", 2, "k", `a"b`)
	r.Observe("h_seconds", 1.5, "u", "x")
	var b strings.Builder
	r.Write(&b)
	out := b.String()
	for _, want := range []string{`c_total{k="a\"b"} 2`, `h_seconds_bucket{u="x",le="1"} 0`, `h_seconds_bucket{u="x",le="2"} 1`, `h_seconds_bucket{u="x",le="+Inf"} 1`, `h_seconds_count{u="x"} 1`} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %s in\n%s", want, out)
		}
	}
}
